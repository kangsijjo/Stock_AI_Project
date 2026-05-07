import FinanceDataReader as fdr
import pandas as pd
from datetime import datetime
from .config import START_DATE
from .db import save_stock

def get_all_tickers():
    """KOSPI + KOSDAQ + S&P500 전체 종목 리스트"""
    tickers = []

    print("KOSPI 종목 리스트 가져오는 중...")
    kospi = fdr.StockListing('KOSPI')[['Code', 'Name', 'Dept']].copy()
    kospi.columns = ['ticker', 'name', 'sector']
    kospi['market'] = 'korea'
    tickers.append(kospi)

    print("KOSDAQ 종목 리스트 가져오는 중...")
    kosdaq = fdr.StockListing('KOSDAQ')[['Code', 'Name', 'Dept']].copy()
    kosdaq.columns = ['ticker', 'name', 'sector']
    kosdaq['market'] = 'korea'
    tickers.append(kosdaq)

    print("S&P500 종목 리스트 가져오는 중...")
    sp500 = fdr.StockListing('S&P500')[['Symbol', 'Name', 'Sector']].copy()
    sp500.columns = ['ticker', 'name', 'sector']
    sp500['market'] = 'usa'
    tickers.append(sp500)

    df = pd.concat(tickers, ignore_index=True)
    print(f"\n총 {len(df)}개 종목 확인완료")
    return df

def collect_all():
    """전체 종목 수집 후 SQLite 저장"""
    end = datetime.today().strftime('%Y-%m-%d')
    all_tickers = get_all_tickers()
    total = len(all_tickers)
    
    print(f"수집 시작 (시작일: {START_DATE})")
    print("처음 한 번은 몇 시간 걸릴 수 있어요.\n")

    for i, row in all_tickers.iterrows():
        ticker = row['ticker']
        name = row['name']
        market = row['market']
        sector = row['sector']

        try:
            print(f"[{i+1}/{total}] [{sector}] {name} ({ticker})")
            df = fdr.DataReader(ticker, START_DATE, end)

            if df is None or len(df) == 0:
                print(f"  데이터 없음, 스킵")
                continue

            df['ticker'] = ticker
            df['name'] = name
            df['sector'] = sector
            df.index.name = 'date'
            df.reset_index(inplace=True)
            save_stock(df, market=market)

        except Exception as e:
            print(f"  실패: {e}")
            continue

    print("\n전체 수집 완료!")

if __name__ == "__main__":
    collect_all()