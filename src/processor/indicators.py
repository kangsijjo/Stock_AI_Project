import pandas as pd
import pandas_ta as ta
import sqlite3
import os
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
    df['macd']        = macd['MACD_12_26_9']
    df['macd_signal'] = macd['MACDs_12_26_9']
    df['macd_hist']   = macd['MACDh_12_26_9']

    # 11-12. 볼린저 밴드
    bb = ta.bbands(df['Close'], length=20)
    bb_cols = bb.columns.tolist()
    df['bb_upper'] = bb[bb_cols[0]]
    df['bb_lower'] = bb[bb_cols[2]]

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

def process_sector(sector, market='korea'):
    """섹터 전체 종목 기술지표 계산 후 DB 저장"""
    conn = get_connection()
    table = 'korea_stocks' if market == 'korea' else 'usa_stocks'

    tickers = pd.read_sql(
        f"SELECT DISTINCT ticker FROM {table} WHERE sector=?",
        conn, params=[sector]
    )['ticker'].tolist()
    conn.close()

    logger.info(f"{sector} 섹터 기술지표 생성 시작 ({len(tickers)}개 종목)")

    for ticker in tickers:
        try:
            conn = get_connection()
            df = pd.read_sql(
                f"SELECT * FROM {table} WHERE ticker=?",
                conn, params=[ticker]
            )
            conn.close()

            if len(df) == 0:
                continue

            df = add_indicators(df)

            conn = get_connection()
            conn.execute(f"DELETE FROM {table} WHERE ticker=?", [ticker])
            df.to_sql(table, conn, if_exists='append', index=False)
            conn.commit()
            conn.close()
            logger.info(f"  완료: {ticker} ({len(df)}행)")

        except Exception as e:
            logger.error(f"  실패: {ticker} - {e}", exc_info=True)

    logger.info(f"{sector} 섹터 완료!")

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