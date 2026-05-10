import FinanceDataReader as fdr
import pandas as pd
import time
from datetime import datetime, timedelta
from .config import START_DATE
from .db import save_stock
from src.config_db import get_connection
from src.logger import get_logger

logger = get_logger('collector')

def get_all_tickers():
    """KOSPI + KOSDAQ + S&P500 전체 종목 리스트"""
    tickers = []

    logger.info("KOSPI 종목 리스트 가져오는 중...")
    try:
        kospi = fdr.StockListing('KOSPI')[['Code', 'Name', 'Dept']].copy()
        kospi.columns = ['ticker', 'name', 'sector']
        kospi['market'] = 'korea'
        tickers.append(kospi)
        logger.info(f"KOSPI {len(kospi)}개 종목 확인")
    except Exception as e:
        logger.error(f"KOSPI 리스트 가져오기 실패: {e}", exc_info=True)

    logger.info("KOSDAQ 종목 리스트 가져오는 중...")
    try:
        kosdaq = fdr.StockListing('KOSDAQ')[['Code', 'Name', 'Dept']].copy()
        kosdaq.columns = ['ticker', 'name', 'sector']
        kosdaq['market'] = 'korea'
        tickers.append(kosdaq)
        logger.info(f"KOSDAQ {len(kosdaq)}개 종목 확인")
    except Exception as e:
        logger.error(f"KOSDAQ 리스트 가져오기 실패: {e}", exc_info=True)

    logger.info("S&P500 종목 리스트 가져오는 중...")
    try:
        sp500 = fdr.StockListing('S&P500')[['Symbol', 'Name', 'Sector']].copy()
        sp500.columns = ['ticker', 'name', 'sector']
        sp500['market'] = 'usa'
        tickers.append(sp500)
        logger.info(f"S&P500 {len(sp500)}개 종목 확인")
    except Exception as e:
        logger.error(f"S&P500 리스트 가져오기 실패: {e}", exc_info=True)

    df = pd.concat(tickers, ignore_index=True)
    logger.info(f"총 {len(df)}개 종목 확인완료")
    return df

def get_latest_dates():
    """DB에 저장된 종목별 가장 최근 날짜 가져오기"""
    conn = get_connection()
    try:
        kr = pd.read_sql(
            "SELECT ticker, MAX(date) as last_date FROM korea_stocks GROUP BY ticker",
            conn
        )
        us = pd.read_sql(
            "SELECT ticker, MAX(date) as last_date FROM usa_stocks GROUP BY ticker",
            conn
        )
        df = pd.concat([kr, us])
        return dict(zip(df['ticker'], df['last_date']))
    except Exception as e:
        logger.warning(f"DB 읽기 실패(처음 실행일 수 있음): {e}")
        return {}
    finally:
        conn.close()

def collect_all():
    """전체 종목 증분 업데이트"""
    end = datetime.today().strftime('%Y-%m-%d')
    all_tickers = get_all_tickers()
    total = len(all_tickers)

    # 종목별 최신 날짜 불러오기
    latest_dates = get_latest_dates()

    logger.info(f"총 {total}개 종목 증분 업데이트 시작 (목표일: {end})")

    failed_tickers = []

    for i, row in all_tickers.iterrows():
        ticker = row['ticker']
        name = row['name']
        market = row['market']
        sector = row['sector']

        # 시작 날짜 결정 (없으면 START_DATE, 있으면 마지막 날짜 +1일)
        if ticker in latest_dates and latest_dates[ticker]:
            last = datetime.strptime(latest_dates[ticker][:10], '%Y-%m-%d')
            fetch_start = (last + timedelta(days=1)).strftime('%Y-%m-%d')
        else:
            fetch_start = START_DATE

        # 이미 최신이면 스킵
        if fetch_start >= end:
            continue

        for attempt in range(3):
            try:
                logger.info(f"[{i+1}/{total}] [{sector}] {name} ({ticker}) | {fetch_start} ~ {end}")
                df = fdr.DataReader(ticker, fetch_start, end)

                if df is None or len(df) == 0:
                    logger.warning(f"새로운 데이터 없음: {ticker}")
                    break

                df['ticker'] = ticker
                df['name'] = name
                df['sector'] = sector
                df.index.name = 'date'
                df.reset_index(inplace=True)
                save_stock(df, market=market)
                break

            except Exception as e:
                logger.warning(f"시도 {attempt+1}/3 실패 [{ticker}]: {e}")
                if attempt < 2:
                    time.sleep(2)
                else:
                    logger.error(f"최종 실패 [{ticker}] {name}: {e}", exc_info=True)
                    failed_tickers.append((ticker, name))

    if failed_tickers:
        logger.warning(f"\n=== 최종 실패 종목 {len(failed_tickers)}개 ===")
        for t, n in failed_tickers:
            logger.warning(f"  {t} {n}")

    logger.info("전체 수집 완료!")

if __name__ == "__main__":
    collect_all()