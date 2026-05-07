import pandas as pd
import pandas_ta as ta
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '../../data/stock.db')

def get_connection():
    return sqlite3.connect(DB_PATH)

def add_indicators(df):
    """기술지표 추가"""
    df = df.copy()
    df = df.sort_values('date').reset_index(drop=True)

    # 이동평균
    df['ma5']  = ta.sma(df['Close'], length=5)
    df['ma20'] = ta.sma(df['Close'], length=20)
    df['ma60'] = ta.sma(df['Close'], length=60)

    # RSI
    df['rsi'] = ta.rsi(df['Close'], length=14)

    # MACD
    macd = ta.macd(df['Close'])
    df['macd']        = macd['MACD_12_26_9']
    df['macd_signal'] = macd['MACDs_12_26_9']
    df['macd_hist']   = macd['MACDh_12_26_9']

    # 볼린저밴드
    bb = ta.bbands(df['Close'], length=20)
    df['bb_upper'] = bb['BBU_20_2.0']
    df['bb_mid']   = bb['BBM_20_2.0']
    df['bb_lower'] = bb['BBL_20_2.0']

    # 거래량 이동평균
    df['vol_ma20'] = ta.sma(df['Volume'], length=20)

    # 거래량 급증 여부 (거래량이 20일 평균의 2배 이상)
    df['vol_spike'] = (df['Volume'] > df['vol_ma20'] * 2).astype(int)

    return df

def process_ticker(ticker, market='korea'):
    """특정 종목 기술지표 계산 후 저장"""
    conn = get_connection()
    table = 'korea_stocks' if market == 'korea' else 'usa_stocks'

    df = pd.read_sql(f"SELECT * FROM {table} WHERE ticker=?", conn, params=[ticker])

    if len(df) == 0:
        print(f"데이터 없음: {ticker}")
        conn.close()
        return

    df = add_indicators(df)

    # 기존 데이터 삭제 후 재저장
    conn.execute(f"DELETE FROM {table} WHERE ticker=?", [ticker])
    df.to_sql(table, conn, if_exists='append', index=False)
    conn.commit()
    conn.close()
    print(f"지표 추가 완료: {ticker} ({len(df)}행)")

def process_sector(sector, market='korea'):
    """섹터 전체 종목 기술지표 계산"""
    conn = get_connection()
    table = 'korea_stocks' if market == 'korea' else 'usa_stocks'

    tickers = pd.read_sql(
        f"SELECT DISTINCT ticker FROM {table} WHERE sector=?",
        conn, params=[sector]
    )['ticker'].tolist()
    conn.close()

    print(f"\n{sector} 섹터 기술지표 생성 시작 ({len(tickers)}개 종목)")
    for ticker in tickers:
        process_ticker(ticker, market)
    print(f"{sector} 섹터 완료!")

if __name__ == "__main__":
    from src.collector.config import ACTIVE_SECTOR
    process_sector(ACTIVE_SECTOR)