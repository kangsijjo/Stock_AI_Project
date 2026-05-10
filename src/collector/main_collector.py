import FinanceDataReader as fdr
import pandas as pd
import time
from datetime import datetime
from .config import START_DATE
from .db import save_stock, get_connection

def get_all_tickers():
    # ... (기존과 완전히 동일) ...
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

# [핵심 수정] 저장된 종목의 '마지막 날짜'를 딕셔너리로 가져오기
def get_latest_dates():
    """DB에 저장된 종목별 가장 최근 날짜 가져오기"""
    conn = get_connection()
    try:
        kr = pd.read_sql("SELECT ticker, MAX(date) as last_date FROM korea_stocks GROUP BY ticker", conn)
        us = pd.read_sql("SELECT ticker, MAX(date) as last_date FROM usa_stocks GROUP BY ticker", conn)
        df = pd.concat([kr, us])
        # { '005930': '2026-05-08', 'AAPL': '2026-05-07', ... } 형태로 반환
        return dict(zip(df['ticker'], df['last_date']))
    except Exception as e:
        print(f"DB 읽기 실패(처음 실행일 수 있음): {e}")
        return {}
    finally:
        conn.close()

def collect_all():
    """종목 수집 및 증분 업데이트"""
    end = datetime.today().strftime('%Y-%m-%d')
    all_tickers = get_all_tickers()
    total = len(all_tickers)
    
    # 1. 종목별 최신 날짜 불러오기
    latest_dates = get_latest_dates()
    
    print(f"\n총 {total}개 종목 증분 업데이트 시작 (목표일: {end})")

    failed_tickers = []

    # 이번엔 필터링하지 않고 전체를 순회하되, 날짜로 스킵함
    for i, row in all_tickers.iterrows():
        ticker = row['ticker']
        name = row['name']
        market = row['market']
        sector = row['sector']

        # 2. 가져올 시작 날짜 결정 (없으면 START_DATE, 있으면 마지막 날짜)
        if ticker in latest_dates:
            fetch_start = latest_dates[ticker][:10] # 'YYYY-MM-DD' 형태
        else:
            fetch_start = START_DATE
            
        # 마지막 저장 날짜가 오늘(목표일)과 같거나 크면 수집 생략
        if fetch_start >= end:
            # 너무 많은 출력을 방지하려면 아래 print는 주석처리해도 좋아
            # print(f"[{i+1}/{total}] {name} - 이미 최신 ({fetch_start})")
            continue

        for attempt in range(3):
            try:
                print(f"[{i+1}/{total}] [{sector}] {name} ({ticker}) | {fetch_start} ~ {end}")
                # [수정] START_DATE 대신 fetch_start 사용
                df = fdr.DataReader(ticker, fetch_start, end)

                if df is None or len(df) == 0:
                    print(f"  새로운 데이터 없음")
                    break

                df['ticker'] = ticker
                df['name'] = name
                df['sector'] = sector
                df.index.name = 'date'
                df.reset_index(inplace=True)
                save_stock(df, market=market)
                break 

            except Exception as e:
                print(f"  시도 {attempt+1}/3 실패: {e}")
                if attempt < 2:
                    time.sleep(2)
                else:
                    print(f"  최종 실패 [{ticker}] {name}")
                    failed_tickers.append((ticker, name))

    if failed_tickers:
        print(f"\n=== 최종 실패 종목 {len(failed_tickers)}개 ===")
        for t, n in failed_tickers:
            print(f"  {t} {n}")

    print("\n업데이트 수집 완료!")

if __name__ == "__main__":
    collect_all()