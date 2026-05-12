import os
import pickle
import pandas as pd
import numpy as np
import sqlite3
import time
from datetime import datetime
from dotenv import load_dotenv
from .kis_api import KISTrader
from .position_manager import (
    init_position_table, add_position,
    check_stop_loss_take_profit, get_performance
)
from src.config_db import get_db_path
from src.logger import get_logger

load_dotenv()
logger = get_logger('auto_trader')
DB_PATH = get_db_path()

from src.config_db import get_connection

def get_latest_features(ticker, market='korea'):
    """indicators 테이블에서 최신 피처 1행 조회"""
    from src.processor.indicators import FEATURE_COLS
    
    conn = get_connection()
    table = 'korea_indicators' if market == 'korea' else 'usa_indicators'

    try:
        df = pd.read_sql(
            f"""SELECT * FROM {table} 
                WHERE ticker=? 
                ORDER BY date DESC 
                LIMIT 1""",
            conn, params=[ticker]
        )
        conn.close()

        if df.empty:
            return None

        # 모델 피처만 추출
        available_cols = [c for c in FEATURE_COLS if c in df.columns]
        if len(available_cols) != len(FEATURE_COLS):
            logger.warning(f"{ticker} 피처 수 불일치: {len(available_cols)}/{len(FEATURE_COLS)}")
            return None

        return df[available_cols]

    except Exception as e:
        logger.error(f"피처 조회 실패 {ticker}: {e}")
        conn.close()
        return None
    
def load_model(sector):
    """모델 로드"""
    model_path = f'src/models/saved/{sector}_model.pkl'
    if not os.path.exists(model_path):
        logger.warning(f"모델 없음: {model_path}")
        return None
    with open(model_path, 'rb') as f:
        return pickle.load(f)

def scan_all_sectors():
    """전체 섹터 스캔 → 매수 신호 종목 반환"""
    usa_sectors = ['Industrials', 'Financials', 'Information Technology',
                   'Health Care', 'Consumer Discretionary', 'Consumer Staples',
                   'Utilities', 'Real Estate', 'Materials',
                   'Communication Services', 'Energy']

    model_dir = 'src/models/saved'
    all_signals = []

    model_files = [f for f in os.listdir(model_dir) if f.endswith('_model.pkl')]

    for model_file in model_files:
        sector = model_file.replace('_model.pkl', '')
        market = 'usa' if sector in usa_sectors else 'korea'

        try:
            with open(f'{model_dir}/{model_file}', 'rb') as f:
                model = pickle.load(f)
        except Exception as e:
            logger.error(f"모델 로드 실패 {sector}: {e}")
            continue

        conn = get_connection()
        table = 'korea_stocks' if market == 'korea' else 'usa_stocks'
        try:
            tickers = pd.read_sql(
                f"SELECT DISTINCT ticker, name FROM {table} WHERE sector=?",
                conn, params=[sector]
            ).values.tolist()
        except Exception as e:
            logger.error(f"종목 조회 실패 {sector}: {e}")
            conn.close()
            continue
        conn.close()

        for ticker, name in tickers:
            features = get_latest_features(ticker, market)
            if features is None:
                continue
            try:
                n_features = model.n_features_in_
                if n_features == 10:
                    features['news_sentiment'] = 0.0
                probs = model.predict_proba(features)[0]
                buy_prob  = probs[1]   # 매수 확률
                sell_prob = probs[2]   # 매도 확률

                if buy_prob >= 0.5:
                    all_signals.append({
                        'ticker': ticker,
                        'name': name,
                        'sector': sector,
                        'market': market,
                        'prob': buy_prob,
                        'signal': 'buy'
                    })
                elif sell_prob >= 0.5:
                    all_signals.append({
                        'ticker': ticker,
                        'name': name,
                        'sector': sector,
                        'market': market,
                        'prob': sell_prob,
                        'signal': 'sell'
                    })
            except Exception as e:
                logger.error(f"예측 실패 {ticker}: {e}")
                continue

    all_signals.sort(key=lambda x: x['prob'], reverse=True)
    return all_signals

def run_auto_trader(mock=True, market_filter=None):
    """자동매매 실행"""
    init_position_table()

    logger.info(f"자동매매 시작 - 모드: {'모의투자' if mock else '실전투자'}")

    trader = KISTrader(mock=mock)
    if not trader.get_token():
        logger.error("토큰 발급 실패")
        return

    # 1. 손절/익절 체크 먼저
    logger.info("손절/익절 체크 중...")
    check_stop_loss_take_profit(trader)

    # 2. 전체 섹터 스캔
    logger.info("전체 섹터 스캔 중...")
    signals = scan_all_sectors()

    # 시장 필터 적용
    if market_filter:
        signals = [s for s in signals if s['market'] == market_filter]

    logger.info(f"매수 신호 {len(signals)}개")
    for i, s in enumerate(signals[:10]):
        logger.info(f"  {i+1}. [{s['sector']}] {s['name']} ({s['ticker']}) - {s['prob']:.2%}")

    if not signals:
        logger.info("매수 신호 없음")
        return

    # 3. TOP 3 매수
    # 매수/매도 신호 분리
    buy_signals  = [s for s in signals if s['signal'] == 'buy']
    sell_signals = [s for s in signals if s['signal'] == 'sell']

    logger.info(f"매수 신호: {len(buy_signals)}개 / 매도 신호: {len(sell_signals)}개")

    # TOP 3 매수
    top3 = buy_signals[:3]
    for s in top3:
        try:
            current_price = trader.get_current_price(s['ticker'])
            if current_price is None:
                continue

            quantity = 1
            if trader.buy(s['ticker'], quantity):
                # 포지션 등록 (익절 10%, 손절 5%)
                add_position(
                    ticker=s['ticker'],
                    name=s['name'],
                    sector=s['sector'],
                    market=s['market'],
                    quantity=quantity,
                    buy_price=current_price,
                    target_profit=0.10,
                    stop_loss=0.05
                )
                logger.info(f"매수 완료: {s['name']} ({s['ticker']}) "
                           f"{quantity}주 @ {current_price:,} - {s['prob']:.2%}")
            time.sleep(0.5)

        except Exception as e:
            logger.error(f"매수 실패 {s['ticker']}: {e}")
            continue

    # 4. 성과 출력
    get_performance()

if __name__ == "__main__":
    run_auto_trader(mock=True, market_filter='korea')