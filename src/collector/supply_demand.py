"""
KRX 외국인/기관 순매수 데이터 수집 — KIS API 우회 버전.

이전 pykrx 기반은 KRX 정보데이터시스템 로그인을 요구해 실패.
대신 한국투자증권 KIS Open Trading API 의 '주식 투자자별 매매동향'
(TR_ID FHKST01010900) 로 종목별 최근 30 거래일 데이터를 한 번에 받는다.

원천 한계:
  - KIS API 는 호출 1회당 최근 30 거래일만 제공
  - 9년 백필 불가 → 오늘부터 매일 1회 호출로 어제 1일치 누적
  - INSERT OR IGNORE 라 같은 (ticker, date) 중복 무해

수동 실행:
  python -m src.collector.supply_demand              # 1회 갱신
  python -m src.collector.supply_demand --real       # 실전 계정 사용
"""
import time
import sys
import argparse
from contextlib import closing

import pandas as pd

from src.config_db import get_connection
from src.logger import get_logger
from src.trader.kis_api import KISTrader

logger = get_logger('supply_demand')

# KIS 모의투자는 실전(~20 req/s)보다 한도가 빡빡함.
# 0.5s 간격(2 req/s) 으로 안정 운영. 3000 종목 = 약 25분.
SLEEP_BETWEEN_CALLS = 1
RETRY_ON_EMPTY     = 2     # 한도 초과 등으로 빈 결과 시 재시도 횟수
RETRY_WAIT_SEC     = 1.2


def _ensure_table(conn):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS supply_demand (
            date TEXT,
            ticker TEXT,
            foreign_net_value REAL,
            institution_net_value REAL,
            short_balance_ratio REAL,
            UNIQUE(date, ticker)
        )
    ''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_sd_date    ON supply_demand(date)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_sd_ticker  ON supply_demand(ticker)')


def _kr_tickers():
    with closing(get_connection()) as conn:
        try:
            df = pd.read_sql("SELECT DISTINCT ticker FROM korea_stocks", conn)
        except Exception:
            return []
    return df['ticker'].tolist()


def _fnum(v):
    try:
        return float(v) if v not in (None, '', '-') else 0.0
    except (TypeError, ValueError):
        return 0.0


def collect_one(trader, ticker, conn):
    """단일 종목 최근 30일치 → supply_demand INSERT OR IGNORE.

    빈 결과(rate limit 응답 등)면 RETRY_ON_EMPTY 만큼 재시도.
    네트워크 예외 자체는 kis_api._http 가 이미 재시도 처리하므로,
    여기서의 재시도는 'rt_cd != 0 으로 인한 빈 결과' 대응이다.
    """
    rows = []
    for attempt in range(RETRY_ON_EMPTY + 1):
        rows = trader.get_investor_daily(ticker)
        if rows:
            break
        if attempt < RETRY_ON_EMPTY:
            time.sleep(RETRY_WAIT_SEC)
    if not rows:
        return 0

    inserts = []
    for r in rows:
        date_raw = (r.get('stck_bsop_date') or '').strip()
        if len(date_raw) < 8:
            continue
        date_iso = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}"
        inserts.append((
            date_iso,
            ticker,
            _fnum(r.get('frgn_ntby_tr_pbmn')),   # 외국인 순매수 금액 (천원)
            _fnum(r.get('orgn_ntby_tr_pbmn')),   # 기관 순매수 금액 (천원)
            None,                                 # 공매도 잔량 — 별도 API (Phase 2 후속)
        ))

    if not inserts:
        return 0

    sql = """INSERT OR IGNORE INTO supply_demand
             (date, ticker, foreign_net_value, institution_net_value, short_balance_ratio)
             VALUES (?, ?, ?, ?, ?)"""
    cur = conn.executemany(sql, inserts)
    return cur.rowcount or 0


def run(mock=True, max_tickers=None):
    trader = KISTrader(mock=mock)
    if not trader.get_token():
        logger.error("토큰 발급 실패 - 중단")
        return

    tickers = _kr_tickers()
    if not tickers:
        logger.warning("종목 리스트 비어 있음")
        return
    if max_tickers:
        tickers = tickers[:max_tickers]

    logger.info(f"수급 수집 시작: 종목 {len(tickers)} (KIS 우회, 종목당 최근 30일)")
    total = 0
    with closing(get_connection()) as conn:
        _ensure_table(conn)
        for i, t in enumerate(tickers, 1):
            total += collect_one(trader, t, conn)
            if i % 100 == 0:
                conn.commit()
                logger.info(f"  진행 {i}/{len(tickers)} (신규 {total}행)")
            time.sleep(SLEEP_BETWEEN_CALLS)
        conn.commit()

    logger.info(f"완료. 신규 {total}행 추가.")


def _parse_args():
    p = argparse.ArgumentParser(description="KIS API 기반 수급 수집")
    p.add_argument('--real', dest='mock', action='store_false', default=True,
                   help='실전 계정 사용 (기본: 모의)')
    p.add_argument('--limit', type=int, default=None, help='테스트용 종목 수 제한')
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run(mock=args.mock, max_tickers=args.limit)
