import FinanceDataReader as fdr
import pandas as pd
import time
from datetime import datetime
from .config import START_DATE
from .db import save_stock
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

import FinanceDataReader as fdr
import pandas as pd
import time
from datetime import datetime
from .config import START_DATE
from .db import save_stock
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

def collect_all():
    """전체 종목 수집 후 SQLite 저장"""
    end = datetime.today().strftime('%Y-%m-%d')
    all_tickers = get_all_tickers()
    total = len(all_tickers)

    logger.info(f"수집 시작 (시작일: {START_DATE})")

    failed_tickers = []  # 실패 종목 저장

    for i, row in all_tickers.iterrows():
        ticker = row['ticker']
        name = row['name']
        market = row['market']
        sector = row['sector']

        success = False
        for attempt in range(3):  # 최대 3번 재시도
            try:
                logger.info(f"[{i+1}/{total}] [{sector}] {name} ({ticker})")
                df = fdr.DataReader(ticker, START_DATE, end)

                if df is None or len(df) == 0:
                    logger.warning(f"데이터 없음, 스킵: {ticker}")
                    success = True
                    break

                df['ticker'] = ticker
                df['name'] = name
                df['sector'] = sector
                df.index.name = 'date'
                df.reset_index(inplace=True)
                save_stock(df, market=market)
                success = True
                break

            except Exception as e:
                logger.warning(f"시도 {attempt+1}/3 실패 [{ticker}]: {e}")
                if attempt < 2:
                    time.sleep(2)  # 2초 후 재시도
                else:
                    logger.error(f"최종 실패 [{ticker}] {name}: {e}", exc_info=True)
                    failed_tickers.append((ticker, name))

    # 실패 종목 요약
    if failed_tickers:
        logger.warning(f"\n=== 최종 실패 종목 {len(failed_tickers)}개 ===")
        for ticker, name in failed_tickers:
            logger.warning(f"  {ticker} {name}")

    logger.info("전체 수집 완료!")

if __name__ == "__main__":
    collect_all()