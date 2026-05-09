import sqlite3
import pandas as pd
import os
from datetime import datetime
from src.config_db import get_db_path
from src.logger import get_logger

logger = get_logger('position_manager')

DB_PATH = get_db_path()

from src.config_db import get_connection

def init_position_table():
    """보유 종목 테이블 초기화"""
    conn = get_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT,
            name TEXT,
            sector TEXT,
            market TEXT,
            quantity INTEGER,
            buy_price REAL,
            buy_date TEXT,
            target_profit REAL DEFAULT 0.10,
            stop_loss REAL DEFAULT 0.05,
            status TEXT DEFAULT 'open'
        )
    ''')
    conn.commit()
    conn.close()
    logger.info("포지션 테이블 초기화 완료")

def add_position(ticker, name, sector, market, quantity, buy_price,
                 target_profit=0.10, stop_loss=0.05):
    """매수 후 포지션 등록"""
    conn = get_connection()
    conn.execute('''
        INSERT INTO positions 
        (ticker, name, sector, market, quantity, buy_price, buy_date, 
         target_profit, stop_loss, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
    ''', [ticker, name, sector, market, quantity, buy_price,
          datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
          target_profit, stop_loss])
    conn.commit()
    conn.close()
    logger.info(f"포지션 등록: {name} ({ticker}) {quantity}주 @ {buy_price:,}원")

def get_open_positions():
    """현재 보유 중인 포지션 조회"""
    conn = get_connection()
    try:
        df = pd.read_sql(
            "SELECT * FROM positions WHERE status='open'",
            conn
        )
    except:
        df = pd.DataFrame()
    conn.close()
    return df

def close_position(position_id, sell_price, reason='manual'):
    """포지션 청산"""
    conn = get_connection()
    conn.execute('''
        UPDATE positions 
        SET status=?, sell_price=?, sell_date=?, close_reason=?
        WHERE id=?
    ''', [f'closed_{reason}', sell_price,
          datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
          reason, position_id])
    conn.commit()
    conn.close()
    logger.info(f"포지션 청산: ID {position_id} @ {sell_price:,}원 ({reason})")

def check_stop_loss_take_profit(trader):
    """손절/익절 체크"""
    init_position_table()
    positions = get_open_positions()

    if positions.empty:
        logger.info("보유 포지션 없음")
        return

    logger.info(f"손절/익절 체크 - {len(positions)}개 포지션")

    for _, pos in positions.iterrows():
        ticker = pos['ticker']
        buy_price = pos['buy_price']
        target_profit = pos['target_profit']
        stop_loss = pos['stop_loss']

        # 현재가 조회
        current_price = trader.get_current_price(ticker)
        if current_price is None:
            continue

        pnl = (current_price - buy_price) / buy_price

        logger.info(f"{pos['name']} ({ticker}): "
                   f"매수가 {buy_price:,} → 현재가 {current_price:,} "
                   f"({pnl*100:+.2f}%)")

        # 익절 체크
        if pnl >= target_profit:
            logger.info(f"익절 실행! {pos['name']} +{pnl*100:.2f}%")
            if trader.sell(ticker, int(pos['quantity'])):
                close_position(pos['id'], current_price, reason='take_profit')

        # 손절 체크
        elif pnl <= -stop_loss:
            logger.info(f"손절 실행! {pos['name']} {pnl*100:.2f}%")
            if trader.sell(ticker, int(pos['quantity'])):
                close_position(pos['id'], current_price, reason='stop_loss')

def get_performance():
    """수익률 성과 조회"""
    conn = get_connection()
    try:
        df = pd.read_sql(
            "SELECT * FROM positions WHERE status LIKE 'closed%'",
            conn
        )
    except:
        conn.close()
        return

    conn.close()

    if df.empty:
        logger.info("청산된 포지션 없음")
        return

    df['pnl'] = (df['sell_price'] - df['buy_price']) / df['buy_price'] * 100
    df['pnl_amount'] = (df['sell_price'] - df['buy_price']) * df['quantity']

    print(f"\n=== 모의투자 성과 ===")
    print(f"총 거래: {len(df)}건")
    print(f"평균 수익률: {df['pnl'].mean():.2f}%")
    print(f"승률: {(df['pnl'] > 0).sum() / len(df) * 100:.1f}%")
    print(f"총 손익: {df['pnl_amount'].sum():,.0f}원")
    print(f"\n익절: {(df['status']=='closed_take_profit').sum()}건")
    print(f"손절: {(df['status']=='closed_stop_loss').sum()}건")
    print(f"수동매도: {(df['status']=='closed_manual').sum()}건")

    print(f"\n=== 거래 내역 ===")
    for _, row in df.iterrows():
        print(f"  {row['name']} ({row['ticker']}): "
              f"{row['pnl']:+.2f}% ({row['close_reason']})")

if __name__ == "__main__":
    init_position_table()
    get_performance()