import pandas as pd
import pandas_ta as ta
import sqlite3
import os
import time
from src.config_db import get_db_path, get_connection
from src.logger import get_logger

logger = get_logger('indicators')
DB_PATH = get_db_path()

def add_indicators(df, macro_df=None, news_df=None, news_weight=0.5):
    """전체 피처 계산 (기술지표 15개 + 거시지표 5개 + 뉴스 1개 = 21개)"""
    df = df.copy().sort_values('date').reset_index(drop=True)

    # === 기술지표 15개 ===
    # 1-3. 이동평균 이격도
    df['ma5']  = ta.sma(df['Close'], length=5)
    df['ma20'] = ta.sma(df['Close'], length=20)
    df['ma60'] = ta.sma(df['Close'], length=60)
    df['ma5_ratio']  = df['Close'] / df['ma5']
    df['ma20_ratio'] = df['Close'] / df['ma20']
    df['ma60_ratio'] = df['Close'] / df['ma60']

    # 4-6. 변화율
    df['return_1d']  = df['Close'].pct_change(1)
    df['return_5d']  = df['Close'].pct_change(5)
    df['return_20d'] = df['Close'].pct_change(20)

    # 7. RSI
    df['rsi'] = ta.rsi(df['Close'], length=14)

    # 8-10. MACD
    macd = ta.macd(df['Close'])
    if macd is not None:
        df['macd']        = macd['MACD_12_26_9']
        df['macd_signal'] = macd['MACDs_12_26_9']
        df['macd_hist']   = macd['MACDh_12_26_9']
    else:
        df['macd'] = df['macd_signal'] = df['macd_hist'] = 0.0

    # 11-12. 볼린저 밴드
    bb = ta.bbands(df['Close'], length=20)
    if bb is not None:
        bb_cols = bb.columns.tolist()
        df['bb_upper'] = bb[bb_cols[0]]
        df['bb_lower'] = bb[bb_cols[2]]
    else:
        df['bb_upper'] = df['bb_lower'] = 0.0

    # 13. 변동성
    df['volatility'] = df['return_1d'].rolling(20).std()

    # 14. 거래량 비율
    df['vol_ratio'] = df['Volume'] / df['Volume'].rolling(20).mean()

    # 15. 거래량 급증
    df['vol_spike'] = (df['Volume'] > df['Volume'].rolling(20).mean() * 2).astype(int)

    # === 거시지표 5개 ===
    if macro_df is not None and not macro_df.empty:
        df['date'] = pd.to_datetime(df['date'])
        macro_df['date'] = pd.to_datetime(macro_df['date'])
        macro_pivot = macro_df.pivot(
            index='date', columns='indicator', values='change_pct'
        ).sort_index().ffill()

        for col, feat in [
            ('NASDAQ',  'nasdaq_chg'),
            ('SOX',     'sox_chg'),
            ('KRW_USD', 'krw_usd_chg'),
            ('VIX',     'vix_chg'),
            ('KOSPI',   'kospi_chg'),
        ]:
            if col in macro_pivot.columns:
                df[feat] = df['date'].map(macro_pivot[col]).ffill().fillna(0.0)
            else:
                df[feat] = 0.0
    else:
        for feat in ['nasdaq_chg', 'sox_chg', 'krw_usd_chg', 'vix_chg', 'kospi_chg']:
            df[feat] = 0.0

    # === 뉴스 감성 1개 ===
    df['news_sentiment'] = 0.0
    if news_df is not None and not news_df.empty:
        try:
            news_df = news_df.copy()
            news_df['pubDate'] = pd.to_datetime(news_df['pubDate'], errors='coerce')
            news_df = news_df.dropna(subset=['pubDate'])
            news_df['date'] = news_df['pubDate'].dt.normalize()

            daily_sentiment = news_df.groupby(['ticker', 'date'])['sentiment'].mean()

            def map_sentiment(row):
                try:
                    return daily_sentiment.loc[(row['ticker'], row['date'])]
                except:
                    return 0.0

            df['date'] = pd.to_datetime(df['date'])
            df['news_sentiment'] = df.apply(map_sentiment, axis=1) * news_weight
        except Exception as e:
            logger.warning(f"뉴스 감성 매핑 실패: {e}")
            df['news_sentiment'] = 0.0

    # FinRL 환경을 위해 날짜 포맷을 다시 문자열로 통일
    df['date'] = df['date'].dt.strftime('%Y-%m-%d')
    return df

# 전체 피처 컬럼 (순서 중요!)
FEATURE_COLS = [
    'return_1d', 'return_5d', 'return_20d',
    'ma5_ratio', 'ma20_ratio', 'ma60_ratio',
    'rsi', 'vol_ratio', 'volatility',
    'macd', 'macd_signal', 'macd_hist',
    'bb_upper', 'bb_lower', 'vol_spike',
    'nasdaq_chg', 'sox_chg', 'krw_usd_chg',
    'vix_chg', 'kospi_chg',
    'news_sentiment'
]

def load_macro():
    conn = get_connection()
    try:
        df = pd.read_sql("SELECT * FROM macro_indicators", conn)
    except:
        df = pd.DataFrame()
    conn.close()
    return df

def load_news(sector, market='korea'):
    conn = get_connection()
    table = 'korea_stocks' if market == 'korea' else 'usa_stocks'
    try:
        tickers = pd.read_sql(
            f"SELECT DISTINCT ticker FROM {table} WHERE sector=?",
            conn, params=[sector]
        )['ticker'].tolist()
        
        if not tickers:
            conn.close()
            return pd.DataFrame()
            
        placeholders = ','.join(['?'] * len(tickers))
        news_df = pd.read_sql(
            f"SELECT ticker, pubDate, sentiment FROM news WHERE ticker IN ({placeholders})",
            conn, params=tickers
        )
    except:
        news_df = pd.DataFrame()
    conn.close()
    return news_df

def process_sector(sector, market='korea'):
    """섹터 전체 종목 21개 피처를 메모리에서 일괄(Batch) 계산 후 DB에 한 번에 저장 (FinRL 표준화)"""
    try:
        from src.collector.config import NEWS_WEIGHT
    except ImportError:
        NEWS_WEIGHT = 0.5

    conn = get_connection()
    stock_table = 'korea_stocks' if market == 'korea' else 'usa_stocks'
    ind_table = 'korea_indicators' if market == 'korea' else 'usa_indicators'

    logger.info(f"{sector} 섹터 21개 피처 Batch Processing 시작 (FinRL 최적화)")
    start_time = time.time()

    # 1. 해당 섹터의 모든 원본 데이터를 한 번에 메모리로 로드 (I/O 병목 제거)
    logger.info("1. 전체 주가 데이터 DB 로드 중...")
    try:
        df_raw = pd.read_sql(f"SELECT * FROM {stock_table} WHERE sector=?", conn, params=[sector])
    except Exception as e:
        logger.error(f"DB 읽기 실패: {e}")
        conn.close()
        return

    if df_raw.empty:
        logger.warning(f"{sector} 섹터의 주가 데이터가 없습니다.")
        conn.close()
        return

    tickers = df_raw['ticker'].unique().tolist()
    logger.info(f"-> 총 {len(tickers)}개 종목, {len(df_raw)}행 로드 완료.")

    # 2. 거시지표 & 뉴스 데이터 로드
    logger.info("2. 거시/뉴스 데이터 로드 중...")
    macro_df = load_macro()
    news_df = load_news(sector, market)

    # 3. 그룹별 지표 일괄 계산 (Pandas Groupby)
    logger.info("3. 메모리 상에서 21개 피처 일괄 연산 중 (Batch)...")
    processed_dfs = []
    
    for ticker, group in df_raw.groupby('ticker'):
        try:
            processed_g = add_indicators(group, macro_df, news_df, NEWS_WEIGHT)
            processed_dfs.append(processed_g)
        except Exception as e:
            logger.error(f"  {ticker} 지표 계산 실패: {e}")

    if not processed_dfs:
        logger.error("계산된 지표 데이터가 없습니다.")
        conn.close()
        return

    df_final = pd.concat(processed_dfs, ignore_index=True)

    # 4. 일괄 DB 저장 (Bulk Insert)
    logger.info(f"4. 가공 완료된 {len(df_final)}행 DB 일괄 저장 중...")
    try:
        # 기존 섹터 데이터 삭제 (중복 방지)
        placeholders = ','.join(['?'] * len(tickers))
        conn.execute(f"DELETE FROM {ind_table} WHERE ticker IN ({placeholders})", tickers)
    except Exception as e:
        pass # 테이블이 없으면 무시하고 생성

    df_final.to_sql(ind_table, conn, if_exists='append', index=False)
    conn.commit()
    conn.close()

    elapsed = time.time() - start_time
    logger.info(f"🎉 {sector} 섹터 Batch 지표 생성 완료! (소요 시간: {elapsed:.2f}초)")

if __name__ == "__main__":
    from src.collector.config import ACTIVE_SECTOR
    usa_sectors = [
        'Industrials', 'Financials', 'Information Technology',
        'Health Care', 'Consumer Discretionary', 'Consumer Staples',
        'Utilities', 'Real Estate', 'Materials',
        'Communication Services', 'Energy'
    ]
    market = 'usa' if ACTIVE_SECTOR in usa_sectors else 'korea'
    process_sector(ACTIVE_SECTOR, market)