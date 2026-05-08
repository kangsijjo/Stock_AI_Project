import pandas as pd
import pandas_ta as ta
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '../../data/stock.db')

def get_connection():
    return sqlite3.connect(DB_PATH)

def add_indicators(df):
    df = df.copy()
    df = df.sort_values('date').reset_index(drop=True)

    df['ma5']  = ta.sma(df['Close'], length=5)
    df['ma20'] = ta.sma(df['Close'], length=20)
    df['ma60'] = ta.sma(df['Close'], length=60)
    df['rsi']  = ta.rsi(df['Close'], length=14)

    macd = ta.macd(df['Close'])
    df['macd']        = macd['MACD_12_26_9']
    df['macd_signal'] = macd['MACDs_12_26_9']
    df['macd_hist']   = macd['MACDh_12_26_9']

    bb = ta.bbands(df['Close'], length=20)
    bb_cols = bb.columns.tolist()
    df['bb_upper'] = bb[bb_cols[0]]
    df['bb_mid']   = bb[bb_cols[1]]
    df['bb_lower'] = bb[bb_cols[2]]

    df['vol_ma20']  = ta.sma(df['Volume'], length=20)
    df['vol_spike'] = (df['Volume'] > df['vol_ma20'] * 2).astype(int)

    return df

def process_ticker(ticker, market='korea'):
    conn = get_connection()
    table = 'korea_stocks' if market == 'korea' else 'usa_stocks'
    temp_table = table + '_temp'

    df = pd.read_sql(f"SELECT * FROM {table} WHERE ticker=?", conn, params=[ticker])

    if len(df) == 0:
        print(f"  데이터 없음: {ticker}")
        conn.close()
        return

    df = add_indicators(df)

    # 임시 테이블에 저장 후 교체
    conn.execute(f"DELETE FROM {table} WHERE ticker=?", [ticker])
    
    # 새 컬럼이 없으면 추가
    existing_cols = pd.read_sql(f"SELECT * FROM {table} LIMIT 1", conn).columns.tolist()
    new_cols = ['ma5', 'ma20', 'ma60', 'rsi', 'macd', 'macd_signal', 'macd_hist',
                'bb_upper', 'bb_mid', 'bb_lower', 'vol_ma20', 'vol_spike']
    
    for col in new_cols:
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} REAL")
    
    conn.commit()
    df.to_sql(table, conn, if_exists='append', index=False)
    conn.commit()
    conn.close()
    print(f"  지표 추가 완료: {ticker} ({len(df)}행)")

def process_sector(sector, market='korea'):
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

    korea_sectors = ['우량기업부', '중견기업부', '벤처기업부', '기술성장기업부']
    market = 'korea' if ACTIVE_SECTOR in korea_sectors else 'usa'

    process_sector(ACTIVE_SECTOR, market)