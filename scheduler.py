import schedule
import time
import os
import pickle
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DB_PATH = 'data/stock.db'

def log(msg):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now}] {msg}")

def get_connection():
    return sqlite3.connect(DB_PATH)

def update_data():
    log("주가 데이터 업데이트 시작")
    os.system("python -m src.collector.main_collector")
    log("주가 데이터 업데이트 완료")

def update_sectors():
    log("섹터 정보 업데이트 시작")
    os.system("python -m src.collector.krx_sector")
    log("섹터 정보 업데이트 완료")

def retrain_all():
    log("전체 섹터 모델 재학습 시작")
    os.system("python main.py all")
    log("전체 섹터 모델 재학습 완료")

def get_latest_features(ticker, market='korea'):
    """최신 피처 생성"""
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
    ma5_ratio  = c[-1] / c[-5:].mean()
    ma20_ratio = c[-1] / c[-20:].mean()
    ma60_ratio = c[-1] / c[-60:].mean()

    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0).rolling(14).mean().iloc[-1]
    loss = (-delta.clip(upper=0)).rolling(14).mean().iloc[-1]
    rsi = 100 - (100 / (1 + gain / loss)) if loss != 0 else 50

    vol_ratio  = v[-1] / v[-20:].mean() if v[-20:].mean() > 0 else 1
    volatility = pd.Series(c).pct_change().rolling(20).std().iloc[-1]

    features = pd.DataFrame([[
        return_1d, return_5d, return_20d,
        ma5_ratio, ma20_ratio, ma60_ratio,
        rsi, vol_ratio, volatility
    ]], columns=[
        'return_1d', 'return_5d', 'return_20d',
        'ma5_ratio', 'ma20_ratio', 'ma60_ratio',
        'rsi', 'vol_ratio', 'volatility'
    ])
    return features

def scan_all_sectors():
    """전체 섹터 스캔 → 최고 종목 TOP3 선정"""
    log("전체 섹터 스캔 시작")

    usa_sectors = ['Industrials', 'Financials', 'Information Technology',
                   'Health Care', 'Consumer Discretionary', 'Consumer Staples',
                   'Utilities', 'Real Estate', 'Materials',
                   'Communication Services', 'Energy']

    model_dir = 'src/models/saved'
    all_signals = []

    # 저장된 모델 목록 가져오기
    if not os.path.exists(model_dir):
        log("모델 없음. 먼저 학습해주세요.")
        return []

    model_files = [f for f in os.listdir(model_dir) if f.endswith('_model.pkl')]

    for model_file in model_files:
        sector = model_file.replace('_model.pkl', '')
        market = 'usa' if sector in usa_sectors else 'korea'

        try:
            with open(f'{model_dir}/{model_file}', 'rb') as f:
                model = pickle.load(f)
        except:
            continue

        conn = get_connection()
        table = 'korea_stocks' if market == 'korea' else 'usa_stocks'
        try:
            tickers = pd.read_sql(
                f"SELECT DISTINCT ticker, name FROM {table} WHERE sector=?",
                conn, params=[sector]
            ).values.tolist()
        except:
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
                prob = model.predict_proba(features)[0][1]
                if prob >= 0.6:
                    all_signals.append({
                        'ticker': ticker,
                        'name': name,
                        'sector': sector,
                        'market': market,
                        'prob': prob
                    })
            except:
                continue

    # 확률 높은 순 정렬
    all_signals.sort(key=lambda x: x['prob'], reverse=True)

    log(f"전체 매수 신호: {len(all_signals)}개")
    log("=== TOP 10 매수 신호 ===")
    for i, s in enumerate(all_signals[:10]):
        log(f"  {i+1}. [{s['sector']}] {s['name']} ({s['ticker']}) - {s['prob']:.2%}")

    return all_signals

def auto_trade_mock():
    """모의투자 자동매매 실행"""
    log("모의투자 자동매매 시작")

    try:
        from src.trader.kis_api import KISTrader
        trader = KISTrader(mock=True)
        if not trader.get_token():
            log("토큰 발급 실패")
            return

        # 잔고 확인
        balance = trader.get_balance()

        # 전체 섹터 스캔
        signals = scan_all_sectors()

        if not signals:
            log("매수 신호 없음")
            return

        # TOP 3 매수
        top3 = signals[:3]
        log(f"\n=== TOP 3 종목 매수 실행 ===")
        for s in top3:
            # 한국 종목만 매수 (모의투자 국내주식)
            if s['market'] == 'korea':
                current_price = trader.get_current_price(s['ticker'])
                if current_price:
                    quantity = 1
                    trader.buy(s['ticker'], quantity)
                    log(f"매수: {s['name']} ({s['ticker']}) {quantity}주 - 상승확률: {s['prob']:.2%}")
                    time.sleep(0.5)

        log("모의투자 자동매매 완료")

    except Exception as e:
        log(f"자동매매 오류: {e}")

def daily_job():
    """매일 08:30 - 데이터 업데이트"""
    log("===== 일일 작업 시작 =====")
    update_data()
    log("===== 일일 작업 완료 =====")

def morning_trade_job():
    """매일 09:00 - 전체 섹터 스캔 + 모의투자"""
    log("===== 모닝 트레이딩 시작 =====")
    auto_trade_mock()
    log("===== 모닝 트레이딩 완료 =====")

def scan_job():
    """전체 섹터 스캔만"""
    log("===== 전체 섹터 스캔 =====")
    scan_all_sectors()
    log("===== 스캔 완료 =====")

def korea_trade_job():
    """한국주식 자동매매"""
    log("===== 한국주식 매매 시작 =====")
    try:
        from src.trader.kis_api import KISTrader
        trader = KISTrader(mock=True)
        if not trader.get_token():
            return

        trader.get_balance()
        signals = scan_all_sectors()
        korea_signals = [s for s in signals if s['market'] == 'korea']

        if not korea_signals:
            log("한국 매수 신호 없음")
            return

        top3 = korea_signals[:3]
        log(f"TOP 3 한국 종목 매수 실행")
        for s in top3:
            current_price = trader.get_current_price(s['ticker'])
            if current_price:
                trader.buy(s['ticker'], 1)
                log(f"매수: {s['name']} ({s['ticker']}) - {s['prob']:.2%}")
                time.sleep(0.5)

    except Exception as e:
        log(f"한국 매매 오류: {e}")
    log("===== 한국주식 매매 완료 =====")

def usa_trade_job():
    """미국주식 자동매매"""
    log("===== 미국주식 매매 시작 =====")
    try:
        from src.trader.kis_api import KISTrader
        trader = KISTrader(mock=True)
        if not trader.get_token():
            return

        trader.get_balance()
        signals = scan_all_sectors()
        usa_signals = [s for s in signals if s['market'] == 'usa']

        if not usa_signals:
            log("미국 매수 신호 없음")
            return

        top3 = usa_signals[:3]
        log(f"TOP 3 미국 종목 매수 실행")
        for s in top3:
            current_price = trader.get_current_price(s['ticker'])
            if current_price:
                trader.buy(s['ticker'], 1)
                log(f"매수: {s['name']} ({s['ticker']}) - {s['prob']:.2%}")
                time.sleep(0.5)

    except Exception as e:
        log(f"미국 매매 오류: {e}")
    log("===== 미국주식 매매 완료 =====")
    
def weekly_job():
    """매주 일요일 09:00 - 전체 재학습"""
    log("===== 주간 작업 시작 =====")
    update_data()
    update_sectors()
    retrain_all()
    log("===== 주간 작업 완료 =====")

def run_all():
    """지금 당장 전체 실행"""
    log("===== 전체 작업 시작 =====")
    update_data()
    update_sectors()
    retrain_all()
    log("===== 전체 작업 완료 =====")

# 스케줄 등록
schedule.every().day.at("06:30").do(daily_job)          # 데이터 업데이트
schedule.every().day.at("06:50").do(scan_job)           # 전체 스캔
schedule.every().day.at("08:00").do(korea_trade_job)    # 한국 매매
schedule.every().day.at("22:20").do(scan_job)           # 미국장 전 스캔
schedule.every().day.at("22:30").do(usa_trade_job)      # 미국 매매
schedule.every().sunday.at("07:00").do(weekly_job)      # 주간 재학습

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == 'all':
        run_all()
    elif len(sys.argv) > 1 and sys.argv[1] == 'trade':
        auto_trade_mock()
    elif len(sys.argv) > 1 and sys.argv[1] == 'scan':
        scan_all_sectors()
    else:
        log("스케줄러 시작")
        log("매일 08:30 데이터 업데이트")
        log("매일 09:00 모닝 트레이딩 (전체 섹터 스캔 + TOP3 매수)")
        log("매주 일요일 09:00 전체 재학습")
        log("종료하려면 Ctrl+C")

        while True:
            schedule.run_pending()
            time.sleep(60)