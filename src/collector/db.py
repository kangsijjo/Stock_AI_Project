import sqlite3
import os
import pandas as pd

from src.config_db import get_db_path
DB_PATH = get_db_path()

def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return sqlite3.connect(DB_PATH)

def save_stock(df, market='korea'):
    """주식 데이터 저장 (중복 제거)"""
    conn = get_connection()
    table = 'korea_stocks' if market == 'korea' else 'usa_stocks'
    
    # 기존 데이터 확인 후 새 데이터만 추가
    try:
        existing = pd.read_sql(f"SELECT date, ticker FROM {table}", conn)
        df_new = df[~df.set_index(['date','ticker']).index.isin(
            existing.set_index(['date','ticker']).index
        )]
    except:
        df_new = df
    
    if len(df_new) > 0:
        df_new.to_sql(table, conn, if_exists='append', index=False)
        print(f"  {len(df_new)}행 저장완료")
    else:
        print(f"  이미 최신 데이터")
    
    conn.close()

def load_sector(sector, market='korea'):
    """섹터 데이터 불러오기"""
    from .config import SECTORS
    
    tickers = [t[0] for t in SECTORS.get(sector, [])]
    table = 'korea_stocks' if market == 'korea' else 'usa_stocks'
    
    conn = get_connection()
    query = f"""
        SELECT * FROM {table} 
        WHERE ticker IN ({','.join(['?']*len(tickers))})
        ORDER BY date
    """
    df = pd.read_sql(query, conn, params=tickers)
    conn.close()
    return df