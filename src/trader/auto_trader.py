import os
import pickle
import pandas as pd
import numpy as np
import sqlite3
import time
from datetime import datetime
from dotenv import load_dotenv
from .kis_api import KISTrader

load_dotenv()

DB_PATH = os.path.join(os.path.dirname(__file__), '../../data/stock.db')

def get_connection():
    return sqlite3.connect(DB_PATH)

def get_latest_features(ticker, market='korea'):
    """DB에서 최신 데이터로 피처 생성"""
    conn = get_connection()
    table = 'korea_stocks' if market == 'korea' else 'usa_stocks'
    
    df = pd.read_sql(
        f"SELECT * FROM {table} WHERE ticker=? ORDER BY date DESC LIMIT 100",
        conn, params=[ticker]
    )
    conn.close()
    
    if len(df) < 61:
        return None
    
    df = df.sort_values('date').reset_index(drop=True)
    c = df['Close'].values
    v = df['Volume'].values
    
    return_1d  = (c[-1] - c[-2]) / c[-2]
    return_5d  = (c[-1] - c[-6]) / c[-6]
    return_20d = (c[-1] - c[-21]) / c[-21]
    
    ma5  = c[-5:].mean()
    ma20 = c[-20:].mean()
    ma60 = c[-60:].mean()
    
    ma5_ratio  = c[-1] / ma5
    ma20_ratio = c[-1] / ma20
    ma60_ratio = c[-1] / ma60
    
    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0).rolling(14).mean().iloc[-1]
    loss = (-delta.clip(upper=0)).rolling(14).mean().iloc[-1]
    rsi = 100 - (100 / (1 + gain / loss)) if loss != 0 else 50
    
    vol_ratio  = v[-1] / v[-20:].mean() if v[-20:].mean() > 0 else 1
    volatility = pd.Series(c).pct_change().rolling(20).std().iloc[-1]
    
    # 피처 이름 맞춰서 DataFrame으로 반환
    # 모델 피처 수에 맞게 자동 조정
    base_features = [
        return_1d, return_5d, return_20d,
        ma5_ratio, ma20_ratio, ma60_ratio,
        rsi, vol_ratio, volatility
    ]
    base_cols = [
        'return_1d', 'return_5d', 'return_20d',
        'ma5_ratio', 'ma20_ratio', 'ma60_ratio',
        'rsi', 'vol_ratio', 'volatility'
    ]

    features = pd.DataFrame([base_features], columns=base_cols)
    
    return features

def load_model(sector):
    """모델 로드"""
    model_path = f'src/models/saved/{sector}_model.pkl'
    if not os.path.exists(model_path):
        print(f"모델 없음: {model_path}")
        return None
    with open(model_path, 'rb') as f:
        return pickle.load(f)

def run_auto_trader(mock=True):
    """자동매매 실행"""
    from src.collector.config import ACTIVE_SECTOR
    
    usa_sectors = ['Industrials', 'Financials', 'Information Technology',
                   'Health Care', 'Consumer Discretionary', 'Consumer Staples',
                   'Utilities', 'Real Estate', 'Materials',
                   'Communication Services', 'Energy']
    market = 'usa' if ACTIVE_SECTOR in usa_sectors else 'korea'
    
    print(f"\n{'='*50}")
    print(f"자동매매 시작 - {ACTIVE_SECTOR} 섹터")
    print(f"모드: {'모의투자' if mock else '실전투자'}")
    print(f"{'='*50}")
    
    # 모델 로드
    model = load_model(ACTIVE_SECTOR)
    if model is None:
        return
    
    # KIS API 초기화
    trader = KISTrader(mock=mock)
    if not trader.get_token():
        return
    
    # 잔고 확인
    trader.get_balance()
    
    # 섹터 종목 리스트
    conn = get_connection()
    table = 'korea_stocks' if market == 'korea' else 'usa_stocks'
    tickers = pd.read_sql(
        f"SELECT DISTINCT ticker, name FROM {table} WHERE sector=?",
        conn, params=[ACTIVE_SECTOR]
    ).values.tolist()
    conn.close()
    
    print(f"\n{len(tickers)}개 종목 분석 중...")
    
    buy_signals  = []
    sell_signals = []
    
    for ticker, name in tickers:
        features = get_latest_features(ticker, market)
        if features is None:
            continue
        
        try:
            # 모델 피처 수 확인 후 맞춤
            n_features = model.n_features_in_
            if n_features == 10:
                features['news_sentiment'] = 0.0
            prob = model.predict_proba(features)[0][1]
            
            if prob >= 0.6:
                buy_signals.append((ticker, name, prob))
            elif prob <= 0.4:
                sell_signals.append((ticker, name, prob))
        except Exception as e:
            print(f"  {ticker} 오류: {e}")
            continue
    
    # 매수 신호 출력
    print(f"\n=== 매수 신호 ({len(buy_signals)}개) ===")
    for ticker, name, prob in sorted(buy_signals, key=lambda x: x[2], reverse=True):
        print(f"  {name} ({ticker}) - 상승확률: {prob:.2%}")
    
    # 매도 신호 출력
    print(f"\n=== 매도 신호 ({len(sell_signals)}개) ===")
    for ticker, name, prob in sorted(sell_signals, key=lambda x: x[2]):
        print(f"  {name} ({ticker}) - 상승확률: {prob:.2%}")
    
    # 자동 주문 여부 확인
    if buy_signals:
        print("\n매수 주문 실행할까요? (y/n): ", end='')
        answer = input().strip().lower()
        
        if answer == 'y':
            trader.get_balance()
            for ticker, name, prob in buy_signals[:3]:
                current_price = trader.get_current_price(ticker)
                if current_price:
                    quantity = 1
                    trader.buy(ticker, quantity)
                    time.sleep(0.5)

if __name__ == "__main__":
    run_auto_trader(mock=True)