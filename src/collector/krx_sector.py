import requests
from bs4 import BeautifulSoup
import pandas as pd
import sqlite3
import os
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.path.join(os.path.dirname(__file__), '../../data/stock.db')

# 네이버 업종 전체 목록
NAVER_SECTORS = {
    '반도체': '278',
    '방산': '284',
    '조선': '291',
    '2차전지': '306',
    '엔터': '285',
    '바이오': '286',
    '제약': '261',
    '자동차': '273',
    '자동차부품': '270',
    '소프트웨어': '287',
    'IT서비스': '267',
    # NOTE: '전기장비' 코드가 '2차전지'와 동일한 306 으로 잘못 매핑되어 있어 제거.
    # 네이버 업종 코드 확인 후 별도 코드(예: 285 외)로 다시 추가할 것.
    '화학': '272',
    '철강': '304',
    '건설': '279',
    '은행': '301',
    '증권': '321',
    '보험': '315',
    '게임': '263',
    '통신': '333',
    '항공': '305',
    '해운': '323',
    '음식료': '268',
}

def get_connection():
    return sqlite3.connect(DB_PATH)

def fetch_sector_tickers(sector_no, sector_name):
    """네이버 금융 업종별 종목 리스트 크롤링"""
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = f"https://finance.naver.com/sise/sise_group_detail.naver?type=upjong&no={sector_no}"
    
    try:
        res = requests.get(url, headers=headers, timeout=5)
        res.encoding = 'euc-kr'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        tickers = []
        rows = soup.select('table.type_5 tr')
        for row in rows:
            link = row.select_one('a[href*="item/main"]')
            if link:
                ticker = link['href'].split('code=')[-1][:6]
                name = link.text.strip()
                tickers.append((ticker, name, sector_name))
        
        return tickers
    except Exception as e:
        print(f"  실패 ({sector_name}): {e}")
        return []

def update_all_sectors():
    """전체 섹터 종목 DB 업데이트"""
    conn = get_connection()
    total_updated = 0
    
    for sector_name, sector_no in NAVER_SECTORS.items():
        print(f"섹터 수집 중: {sector_name}")
        tickers = fetch_sector_tickers(sector_no, sector_name)
        
        if not tickers:
            print(f"  종목 없음")
            continue
        
        for ticker, name, sector in tickers:
            conn.execute(
                "UPDATE korea_stocks SET sector=? WHERE ticker=?",
                [sector, ticker]
            )
        
        conn.commit()
        print(f"  {len(tickers)}개 종목 섹터 업데이트 완료")
        total_updated += len(tickers)
    
    conn.close()
    print(f"\n전체 {total_updated}개 종목 섹터 업데이트 완료!")

if __name__ == "__main__":
    update_all_sectors()