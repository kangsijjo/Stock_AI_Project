import sqlite3
import os
import pandas as pd

from src.config_db import get_db_path
DB_PATH = get_db_path()

from src.config_db import get_connection

def save_stock(df, market='korea'):
    """주식 데이터 저장 (초고속 인덱스 활용)"""
    if df.empty:
        return
        
    conn = get_connection()
    table = 'korea_stocks' if market == 'korea' else 'usa_stocks'
    
    # 1. 현재 수집한 데이터의 종목코드와 가장 빠른 날짜 확인
    ticker = df['ticker'].iloc[0]
    start_date = df['date'].min()
    
    # 2. 딱 '해당 종목'의 겹칠 가능성 있는 날짜만 초고속 검색
    try:
        query = f"SELECT date FROM {table} WHERE ticker=? AND date>=?"
        existing = pd.read_sql(query, conn, params=[ticker, start_date])
        
        if not existing.empty:
            # 중복되는 날짜는 빼고 순수 새 데이터만 필터링
            df_new = df[~df['date'].isin(existing['date'])]
        else:
            df_new = df
    except:
        # 테이블이 처음 만들어질 때
        df_new = df
    
    # 3. DB에 저장
    if len(df_new) > 0:
        df_new.to_sql(table, conn, if_exists='append', index=False)
        print(f"  {len(df_new)}행 저장완료")
    else:
        print(f"  이미 최신 데이터")
    
    conn.close()

def load_sector(sector, market='korea'):
    """섹터 데이터 불러오기"""
    table = 'korea_stocks' if market == 'korea' else 'usa_stocks'
    
    conn = get_connection()
    query = f"SELECT * FROM {table} WHERE sector=? ORDER BY date"
    df = pd.read_sql(query, conn, params=[sector])
    conn.close()
    
    return df