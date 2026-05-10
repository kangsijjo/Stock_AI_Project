import requests
from bs4 import BeautifulSoup
import pandas as pd
import sqlite3
import os
import time
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '../../data/stock.db')

def get_connection():
    return sqlite3.connect(DB_PATH)

def get_sector_tickers(sector):
    """DB에서 해당 섹터 종목 자동으로 가져오기"""
    conn = get_connection()
    try:
        df = pd.read_sql("SELECT DISTINCT ticker, name, sector FROM korea_stocks WHERE sector=?", conn, params=[sector])
        if len(df) > 0: return df[['ticker', 'name']].values.tolist(), 'korea'
    except: pass
    try:
        df = pd.read_sql("SELECT DISTINCT ticker, name, sector FROM usa_stocks WHERE sector=?", conn, params=[sector])
        if len(df) > 0: return df[['ticker', 'name']].values.tolist(), 'usa'
    except: pass
    conn.close()
    return [], None

def fetch_naver_finance_news(ticker, name, max_pages=3):
    """네이버 금융 종목 뉴스 크롤링 (재시도 로직 추가)"""
    headers = {'User-Agent': 'Mozilla/5.0'}
    news_list = []

    for page in range(1, max_pages + 1):
        url = f"https://finance.naver.com/item/news_news.naver?code={ticker}&page={page}"
        for attempt in range(3):
            try:
                res = requests.get(url, headers=headers, timeout=5)
                res.encoding = 'euc-kr'
                soup = BeautifulSoup(res.text, 'html.parser')
                rows = soup.select('table.type5 tr')

                for row in rows:
                    title_tag = row.select_one('td.title a')
                    date_tag = row.select_one('td.date')
                    if title_tag and date_tag:
                        news_list.append({
                            'ticker': ticker,
                            'name': name,
                            'title': title_tag.text.strip(),
                            'link': 'https://finance.naver.com' + title_tag['href'],
                            'pubDate': date_tag.text.strip(),
                            'collected_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        })
                break
            except Exception as e:
                print(f"  실패 ({ticker} page{page}, 시도 {attempt+1}/3): {e}")
                if attempt < 2: time.sleep(2)
                else: continue
    return news_list

def fetch_yahoo_news(ticker, name):
    """미국 주식 야후 파이낸스 뉴스 (재시도 로직 추가)"""
    headers = {'User-Agent': 'Mozilla/5.0'}
    news_list = []
    url = f"https://finance.yahoo.com/rss/headline?s={ticker}"
    
    for attempt in range(3):
        try:
            res = requests.get(url, headers=headers, timeout=5)
            soup = BeautifulSoup(res.content, 'xml')
            items = soup.find_all('item')[:20]
            
            for item in items:
                news_list.append({
                    'ticker': ticker,
                    'name': name,
                    'title': item.find('title').text if item.find('title') else '',
                    'link': item.find('link').text if item.find('link') else '',
                    'pubDate': item.find('pubDate').text if item.find('pubDate') else '',
                    'collected_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
            break
        except Exception as e:
            print(f"  실패 ({ticker}, 시도 {attempt+1}/3): {e}")
            if attempt < 2: time.sleep(2)
    return news_list

def save_news(news_list):
    if not news_list:
        print("저장할 뉴스 없음")
        return
    df = pd.DataFrame(news_list)
    conn = get_connection()
    df.to_sql('news', conn, if_exists='append', index=False)
    conn.close()
    print(f"뉴스 {len(df)}개 저장완료")

def collect_news():
    from src.collector.config import ACTIVE_SECTOR
    print(f"\n=== {ACTIVE_SECTOR} 섹터 뉴스 수집 시작 ===")
    tickers, market = get_sector_tickers(ACTIVE_SECTOR)
    
    if not tickers:
        print(f"DB에 {ACTIVE_SECTOR} 섹터 데이터 없음. 수집 먼저 완료해주세요.")
        return
    
    print(f"{len(tickers)}개 종목 뉴스 수집 중...")
    all_news = []
    for ticker, name in tickers:
        print(f"수집 중: {name} ({ticker})")
        if market == 'korea': news = fetch_naver_finance_news(ticker, name)
        else: news = fetch_yahoo_news(ticker, name)
        print(f"  {len(news)}개 수집")
        all_news.extend(news)
    
    save_news(all_news)
    print(f"\n=== {ACTIVE_SECTOR} 뉴스 수집 완료 ===")

if __name__ == "__main__":
    collect_news()