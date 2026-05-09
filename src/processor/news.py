import requests
from bs4 import BeautifulSoup
import pandas as pd
import sqlite3
import os
from datetime import datetime
from transformers import pipeline

from src.config_db import get_db_path
DB_PATH = get_db_path()
from src.config_db import get_connection

# FinBERT 감성분석 모델 로드
print("FinBERT 모델 로딩 중...")
kr_sentiment = pipeline(
    "sentiment-analysis",
    model="snunlp/KR-FinBert-SC",
    truncation=True,
    max_length=512
)
en_sentiment = pipeline(
    "sentiment-analysis",
    model="ProsusAI/finbert",
    truncation=True,
    max_length=512
)
print("FinBERT 모델 로딩 완료!")



def fetch_naver_finance_news(ticker, name, max_pages=3):
    """네이버 금융 종목 뉴스 크롤링"""
    headers = {'User-Agent': 'Mozilla/5.0'}
    news_list = []

    for page in range(1, max_pages + 1):
        url = f"https://finance.naver.com/item/news_news.naver?code={ticker}&page={page}"
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
        except Exception as e:
            print(f"  실패 ({ticker} page{page}): {e}")
            continue

    return news_list

def fetch_yahoo_news(ticker, name):
    """미국 주식 야후 파이낸스 뉴스"""
    headers = {'User-Agent': 'Mozilla/5.0'}
    news_list = []
    url = f"https://finance.yahoo.com/rss/headline?s={ticker}"

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
    except Exception as e:
        print(f"  실패 ({ticker}): {e}")

    return news_list

def is_korean(text):
    """한국어 여부 판단"""
    korean_chars = sum(1 for c in text if '\uAC00' <= c <= '\uD7A3')
    return korean_chars > len(text) * 0.2

def analyze_sentiment(texts, market='korea'):
    """FinBERT로 감성분석 (한국어/영어 자동 구분)"""
    scores = []
    for text in texts:
        try:
            # 한국어면 한국 모델, 영어면 영어 모델
            model = kr_sentiment if is_korean(text) else en_sentiment
            result = model(text)[0]
            label = result['label']
            score = result['score']

            # 점수 변환: positive=+score, negative=-score, neutral=0
            if label == 'positive':
                scores.append(score)
            elif label == 'negative':
                scores.append(-score)
            else:
                scores.append(0.0)
        except:
            scores.append(0.0)
    return scores

def save_news_with_sentiment(news_list, market='korea'):
    """뉴스 + 감성점수 저장"""
    if not news_list:
        print("저장할 뉴스 없음")
        return

    df = pd.DataFrame(news_list)

    # 감성분석
    print(f"  감성분석 중 ({len(df)}개)...")
    titles = df['title'].tolist()
    df['sentiment'] = analyze_sentiment(titles, market)
    df['sentiment_avg'] = df['sentiment'].mean()

    conn = get_connection()
    df.to_sql('news', conn, if_exists='append', index=False)
    conn.close()
    print(f"  뉴스 {len(df)}개 저장완료 (평균 감성: {df['sentiment'].mean():.3f})")

def collect_news():
    """config.py의 ACTIVE_SECTOR 기준으로 자동 뉴스 수집"""
    from src.collector.config import ACTIVE_SECTOR

    usa_sectors = ['Industrials', 'Financials', 'Information Technology',
                   'Health Care', 'Consumer Discretionary', 'Consumer Staples',
                   'Utilities', 'Real Estate', 'Materials',
                   'Communication Services', 'Energy']
    market = 'usa' if ACTIVE_SECTOR in usa_sectors else 'korea'

    print(f"\n=== {ACTIVE_SECTOR} 섹터 뉴스 수집 시작 ===")

    conn = get_connection()
    table = 'korea_stocks' if market == 'korea' else 'usa_stocks'
    tickers = pd.read_sql(
        f"SELECT DISTINCT ticker, name FROM {table} WHERE sector=?",
        conn, params=[ACTIVE_SECTOR]
    ).values.tolist()
    conn.close()

    if not tickers:
        print(f"DB에 {ACTIVE_SECTOR} 섹터 데이터 없음")
        return

    print(f"{len(tickers)}개 종목 뉴스 수집 중...")
    all_news = []

    for ticker, name in tickers:
        print(f"수집 중: {name} ({ticker})")
        if market == 'korea':
            news = fetch_naver_finance_news(ticker, name)
        else:
            news = fetch_yahoo_news(ticker, name)
        print(f"  {len(news)}개 수집")
        all_news.extend(news)

    save_news_with_sentiment(all_news)
    print(f"\n=== {ACTIVE_SECTOR} 뉴스 수집 완료 ===")

if __name__ == "__main__":
    collect_news()