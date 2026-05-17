import sqlite3
import pandas as pd
import os
from datetime import datetime, timedelta
from src.config_db import get_db_path
from src.logger import get_logger

# 학습 타깃(5일 후 등락)과 거래 룰을 일치시키기 위한 기본 보유일.
DEFAULT_HOLDING_DAYS = 5

logger = get_logger('position_manager')

DB_PATH = get_db_path()

from src.config_db import get_connection

def init_position_table():
    """보유 종목 테이블 초기화 (+ 기존 DB에 holding_days 컬럼 자동 추가)"""
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
            holding_days INTEGER DEFAULT 5,
            status TEXT DEFAULT 'open'
        )
    ''')
    # 이미 만들어진 구버전 DB 에 holding_days 컬럼이 없으면 추가.
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(positions)").fetchall()]
        if 'holding_days' not in cols:
            conn.execute("ALTER TABLE positions ADD COLUMN holding_days INTEGER DEFAULT 5")
    except Exception as e:
        logger.warning(f"holding_days 컬럼 마이그레이션 스킵: {e}")
    conn.commit()
    conn.close()
    logger.info("포지션 테이블 초기화 완료")

def add_position(ticker, name, sector, market, quantity, buy_price,
                 target_profit=0.10, stop_loss=0.05,
                 holding_days=DEFAULT_HOLDING_DAYS):
    """매수 후 포지션 등록 (학습 타깃 horizon=holding_days 와 정합)"""
    conn = get_connection()
    conn.execute('''
        INSERT INTO positions
        (ticker, name, sector, market, quantity, buy_price, buy_date,
         target_profit, stop_loss, holding_days, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
    ''', [ticker, name, sector, market, quantity, buy_price,
          datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
          target_profit, stop_loss, holding_days])
    conn.commit()
    conn.close()
    logger.info(
        f"포지션 등록: {name} ({ticker}) {quantity}주 @ {buy_price:,}원 "
        f"(보유 {holding_days}일)"
    )

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

def _business_days_since(buy_date_str):
    """매수일~오늘 영업일(주말 제외) 카운트. KR/US 휴장일까지 엄밀히 보려면
    별도 캘린더가 필요하지만, 1차 근사로는 weekday 카운트로 충분."""
    try:
        buy_dt = datetime.strptime(buy_date_str[:10], '%Y-%m-%d')
    except Exception:
        return 0
    today = datetime.now()
    days = 0
    cur = buy_dt + timedelta(days=1)
    while cur.date() <= today.date():
        if cur.weekday() < 5:
            days += 1
        cur += timedelta(days=1)
    return days


def check_stop_loss_take_profit(trader):
    """
    청산 룰 우선순위:
      1) 손절(stop_loss) 도달
      2) 익절(target_profit) 도달
      3) 보유일(holding_days) 경과 → 시간 청산 (학습 타깃 horizon 과 정합)
    """
    init_position_table()
    positions = get_open_positions()

    if positions.empty:
        logger.info("보유 포지션 없음")
        return

    logger.info(f"청산 체크 - {len(positions)}개 포지션")

    for _, pos in positions.iterrows():
        ticker        = pos['ticker']
        buy_price     = pos['buy_price']
        target_profit = pos['target_profit']
        stop_loss     = pos['stop_loss']
        holding_days  = int(pos['holding_days']) if 'holding_days' in pos and pd.notna(pos['holding_days']) \
                        else DEFAULT_HOLDING_DAYS

        current_price = trader.get_current_price(ticker)
        if current_price is None:
            continue

        pnl = (current_price - buy_price) / buy_price
        held = _business_days_since(str(pos['buy_date']))

        # 폴링 호출 시 변화 없는 종목의 로그 도배 방지:
        # 손절/익절 ±1.0%p 임계 근접 또는 보유기간 만료 임박 시에만 INFO.
        msg = (f"{pos['name']} ({ticker}): {buy_price:,} → {current_price:,} "
               f"({pnl*100:+.2f}%) | 보유 {held}/{holding_days}영업일")
        if (pnl <= -stop_loss + 0.01) or (pnl >= target_profit - 0.01) \
                or (held >= holding_days - 1):
            logger.info(msg)
        else:
            logger.debug(msg)

        # 1) 손절
        if pnl <= -stop_loss:
            logger.info(f"손절 실행! {pos['name']} {pnl*100:.2f}%")
            if trader.sell(ticker, int(pos['quantity'])):
                close_position(pos['id'], current_price, reason='stop_loss')
            continue

        # 2) 익절
        if pnl >= target_profit:
            logger.info(f"익절 실행! {pos['name']} +{pnl*100:.2f}%")
            if trader.sell(ticker, int(pos['quantity'])):
                close_position(pos['id'], current_price, reason='take_profit')
            continue

        # 3) 보유기간 만료 (학습 타깃 5일 horizon 과 동일)
        if held >= holding_days:
            logger.info(f"시간 청산! {pos['name']} {pnl*100:+.2f}% ({held}영업일)")
            if trader.sell(ticker, int(pos['quantity'])):
                close_position(pos['id'], current_price, reason='time_exit')

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