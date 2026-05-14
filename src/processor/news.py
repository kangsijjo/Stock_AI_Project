import requests
from bs4 import BeautifulSoup
import pandas as pd
import os
import time
from datetime import datetime
from dotenv import load_dotenv
from transformers import pipeline
from src.config_db import get_connection, get_db_path
from src.logger import get_logger

load_dotenv()
logger = get_logger('news')
DB_PATH = get_db_path()

DART_API_KEY = os.getenv('DART_API_KEY')

# FinBERT 모델 로드
logger.info("FinBERT 모델 로딩 중...")
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
logger.info("FinBERT 모델 로딩 완료!")

def is_korean(text):
    korean_chars = sum(1 for c in text if '\uAC00' <= c <= '\uD7A3')
    return korean_chars > len(text) * 0.2

def analyze_sentiment(texts, sources=None):
    """FinBERT + DART 전용 키워드 하이브리드 감성분석"""
    # 🎯 DART 공시 전용 확정 호재/악재 키워드 룰
    dart_rules = {
        # 초강력 악재 (-1.0 ~ -0.8)
        '유상증자결정': -0.8, '감자결정': -1.0, '상장폐지': -1.0, 
        '영업정지': -1.0, '파산': -1.0, '해산사유발생': -1.0,
        # 주주가치 희석 악재 (-0.5)
        '전환사채권발행결정': -0.5, '신주인수권부사채권발행결정': -0.5,
        # 초강력 호재 (+0.7 ~ +1.0)
        '무상증자결정': 0.8, '단일판매ㆍ공급계약체결': 0.8, 
        '주식소각결정': 0.9, '자기주식취득결정': 0.7, '영업잠정실적(공정공시)': 0.5,
        # 노이즈/스팸 처리 (0.0) - 무조건 중립 처리하여 모델 혼동 방지
        '소유상황보고서': 0.0, '주식등의대량보유상황보고서': 0.0, 
        '임원ㆍ주요주주': 0.0, '주주총회소집': 0.0, '기업설명회': 0.0
    }

    scores = []
    for i, text in enumerate(texts):
        source = sources[i] if sources is not None else 'Yahoo'
        rule_matched = False

        # 1. DART 공시일 경우 룰베이스 필터 먼저 적용
        if source == 'DART':
            clean_text = text.replace(' ', '') # 띄어쓰기 무시하고 매칭
            for keyword, score in dart_rules.items():
                if keyword in clean_text:
                    scores.append(score)
                    rule_matched = True
                    break
        
        if rule_matched:
            continue

        # 2. 룰에 없는 일반 뉴스나 공시는 기존 FinBERT로 분석
        try:
            model = kr_sentiment if is_korean(text) else en_sentiment
            result = model(text)[0]
            label = result['label']
            score = result['score']
            if label == 'positive':
                scores.append(score)
            elif label == 'negative':
                scores.append(-score)
            else:
                scores.append(0.0)
        except:
            scores.append(0.0)
            
    return scores

def get_corp_code(ticker):
    """종목코드로 DART 고유번호 조회"""
    url = "https://opendart.fss.or.kr/api/company.json"
    params = {
        'crtfc_key': DART_API_KEY,
        'stock_code': ticker
    }
    try:
        res = requests.get(url, params=params, timeout=5)
        data = res.json()
        if data.get('status') == '000':
            return data.get('corp_code')
    except Exception as e:
        logger.error(f"DART 고유번호 조회 실패 {ticker}: {e}")
    return None

def fetch_dart_disclosures(ticker, name, days=1):
    """DART 공시 수집"""
    corp_code = get_corp_code(ticker)
    if not corp_code:
        return []

    url = "https://opendart.fss.or.kr/api/list.json"
    params = {
        'crtfc_key': DART_API_KEY,
        'corp_code': corp_code,
        'page_count': 20,
        'sort': 'date',
        'sort_mth': 'desc'
    }

    try:
        res = requests.get(url, params=params, timeout=5)
        data = res.json()

        if data.get('status') != '000':
            return []

        news_list = []
        for item in data.get('list', []):
            news_list.append({
                'ticker': ticker,
                'name': name,
                'title': item.get('report_nm', ''),
                'link': f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item.get('rcept_no')}",
                'pubDate': item.get('rcept_dt', ''),
                'collected_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'source': 'DART'
            })
        return news_list

    except Exception as e:
        logger.error(f"DART 공시 수집 실패 {ticker}: {e}")
        return []

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
                'collected_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'source': 'Yahoo'
            })
    except Exception as e:
        logger.error(f"야후 뉴스 수집 실패 {ticker}: {e}")

    return news_list

def save_news(news_list):
    """뉴스 + 감성분석 저장"""
    if not news_list:
        return

    df = pd.DataFrame(news_list)

    # 💡 [핵심 패치] 감성분석 시 source 정보 같이 넘겨주기
    logger.info(f"  감성분석 중 ({len(df)}개)...")
    df['sentiment'] = analyze_sentiment(df['title'].tolist(), df['source'].tolist())
    df['sentiment_avg'] = df['sentiment'].mean()

    conn = get_connection()
    df.to_sql('news', conn, if_exists='append', index=False)
    conn.close()
    logger.info(f"  {len(df)}개 저장완료 (평균 감성: {df['sentiment'].mean():.3f})")

def get_sector_tickers(sector):
    """섹터 종목 리스트 조회"""
    conn = get_connection()

    try:
        df = pd.read_sql(
            "SELECT DISTINCT ticker, name FROM korea_stocks WHERE sector=?",
            conn, params=[sector]
        )
        if len(df) > 0:
            conn.close()
            return df[['ticker', 'name']].values.tolist(), 'korea'
    except:
        pass

    try:
        df = pd.read_sql(
            "SELECT DISTINCT ticker, name FROM usa_stocks WHERE sector=?",
            conn, params=[sector]
        )
        if len(df) > 0:
            conn.close()
            return df[['ticker', 'name']].values.tolist(), 'usa'
    except:
        pass

    conn.close()
    return [], None

def collect_dart_realtime():
    """30분마다 실행 - 활성 섹터 공시 수집"""
    from src.collector.config import ACTIVE_SECTOR

    logger.info(f"=== [{ACTIVE_SECTOR}] DART 실시간 공시 수집 ===")
    tickers, market = get_sector_tickers(ACTIVE_SECTOR)

    if not tickers or market != 'korea':
        logger.warning("한국 섹터만 DART 공시 수집 가능")
        return

    all_news = []
    for ticker, name in tickers:
        news = fetch_dart_disclosures(ticker, name)
        if news:
            logger.info(f"  {name} ({ticker}): {len(news)}개 공시")
            all_news.extend(news)

    save_news(all_news)
    logger.info(f"=== DART 공시 수집 완료: {len(all_news)}개 ===")

def collect_dart_historical(sector=None, start_date='20150101'):
    """과거 공시 전체 수집"""
    from src.collector.config import ACTIVE_SECTOR, KOREA_SECTORS
    
    if sector == 'all':
        sectors = KOREA_SECTORS
    else:
        sectors = [sector if sector else ACTIVE_SECTOR]
    
    for s in sectors:
        logger.info(f"=== [{s}] 과거 공시 수집 시작 ({start_date}~) ===")
        tickers, market = get_sector_tickers(s)
        
        if not tickers or market != 'korea':
            logger.warning(f"{s} 스킵 (한국 섹터만 가능)")
            continue
        
        total = len(tickers)
        all_news = []
        
        for i, (ticker, name) in enumerate(tickers):
            logger.info(f"  [{i+1}/{total}] {name} ({ticker}) 공시 수집 중...")
            
            corp_code = get_corp_code(ticker)
            if not corp_code:
                continue
            
            # 페이지별 수집
            page = 1
            while True:
                url = "https://opendart.fss.or.kr/api/list.json"
                params = {
                    'crtfc_key': DART_API_KEY,
                    'corp_code': corp_code,
                    'bgn_de': start_date,
                    'page_no': page,
                    'page_count': 100,
                    'sort': 'date',
                    'sort_mth': 'asc'
                }
                
                try:
                    res = requests.get(url, params=params, timeout=10)
                    data = res.json()
                    
                    if data.get('status') != '000':
                        break
                    
                    items = data.get('list', [])
                    if not items:
                        break
                    
                    for item in items:
                        all_news.append({
                            'ticker': ticker,
                            'name': name,
                            'title': item.get('report_nm', ''),
                            'link': f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item.get('rcept_no')}",
                            'pubDate': item.get('rcept_dt', ''),
                            'collected_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            'source': 'DART'
                        })
                    
                    # 마지막 페이지 확인
                    total_pages = int(data.get('total_page', 1))
                    if page >= total_pages:
                        break
                    page += 1
                    time.sleep(0.3)  # API 호출 제한
                    
                except Exception as e:
                    logger.error(f"  {ticker} 페이지 {page} 실패: {e}")
                    break
            
            logger.info(f"  {name}: {len([n for n in all_news if n['ticker']==ticker])}개 공시")
        
        # 배치로 저장 (500개씩)
        batch_size = 500
        for i in range(0, len(all_news), batch_size):
            batch = all_news[i:i+batch_size]
            save_news(batch)
            logger.info(f"  {i+batch_size}/{len(all_news)}개 저장 완료")
        
        logger.info(f"=== [{s}] 과거 공시 수집 완료: {len(all_news)}개 ===")

def collect_news():
    """전체 섹터 뉴스 수집 (일 1회)"""
    from src.collector.config import KOREA_SECTORS, USA_SECTORS

    usa_sectors_list = ['Industrials', 'Financials', 'Information Technology',
                        'Health Care', 'Consumer Discretionary', 'Consumer Staples',
                        'Utilities', 'Real Estate', 'Materials',
                        'Communication Services', 'Energy']

    all_sectors = KOREA_SECTORS + USA_SECTORS
    total = len(all_sectors)

    for i, sector in enumerate(all_sectors):
        market = 'usa' if sector in usa_sectors_list else 'korea'

        print(f"\n=== [{i+1}/{total}] {sector} 섹터 뉴스 수집 시작 ===")
        tickers, mkt = get_sector_tickers(sector)

        if not tickers:
            print(f"  DB에 {sector} 섹터 데이터 없음. 스킵.")
            continue

        print(f"  {len(tickers)}개 종목 수집 중...")
        all_news = []

        for ticker, name in tickers:
            if market == 'korea':
                news = fetch_dart_disclosures(ticker, name)
            else:
                news = fetch_yahoo_news(ticker, name)
            print(f"  {name} ({ticker}): {len(news)}개")
            all_news.extend(news)

        save_news(all_news)
        print(f"=== {sector} 완료: {len(all_news)}개 ===")

    print(f"\n전체 {total}개 섹터 뉴스 수집 완료!")

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'daily'

    if cmd == 'realtime':
        collect_dart_realtime()
    elif cmd == 'historical':
        sector_arg = sys.argv[2] if len(sys.argv) > 2 else None
        collect_dart_historical(sector=sector_arg)
    else:
        collect_news()