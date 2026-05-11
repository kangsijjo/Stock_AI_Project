import pandas as pd
import pickle
import os
from src.config_db import get_db_path, get_connection
from src.processor.indicators import add_indicators
from src.logger import get_logger

logger = get_logger('backtest')
DB_PATH = get_db_path()

def load_macro():
    conn = get_connection()
    try:
        df = pd.read_sql("SELECT * FROM macro_indicators", conn)
        conn.close()
        return df
    except:
        conn.close()
        return pd.DataFrame()

def load_news(sector, market):
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
        conn.close()
        return news_df
    except:
        conn.close()
        return pd.DataFrame()

def run_backtest(sector=None, market=None):
    from src.collector.config import ACTIVE_SECTOR, NEWS_WEIGHT

    if sector is None:
        sector = ACTIVE_SECTOR

    if market is None:
        usa_sectors = [
            'Industrials', 'Financials', 'Information Technology',
            'Health Care', 'Consumer Discretionary', 'Consumer Staples',
            'Utilities', 'Real Estate', 'Materials',
            'Communication Services', 'Energy'
        ]
        market = 'usa' if sector in usa_sectors else 'korea'

    logger.info(f"=== {sector} 백테스트 시작 ===")

    # 모델 로드
    model_path = f'src/models/saved/{sector}_model.pkl'
    if not os.path.exists(model_path):
        logger.error(f"모델 없음: {model_path}")
        return

    with open(model_path, 'rb') as f:
        model = pickle.load(f)

    # 데이터 로드
    conn = get_connection()
    table = 'korea_stocks' if market == 'korea' else 'usa_stocks'
    df = pd.read_sql(
        f"SELECT * FROM {table} WHERE sector=? ORDER BY ticker, date",
        conn, params=[sector]
    )
    conn.close()

    if len(df) == 0:
        logger.error("데이터 없음")
        return

    logger.info(f"데이터 로드: {len(df)}행")

    # 거시지표 + 뉴스 로드
    macro_df = load_macro()
    news_df  = load_news(sector, market)

    # indicators.py로 피처 생성
    logger.info("피처 생성 중...")
    features = []
    for ticker, group in df.groupby('ticker'):
        g = group.copy()
        g = add_indicators(g, macro_df, news_df, NEWS_WEIGHT)
        features.append(g)

    df = pd.concat(features, ignore_index=True)

    # 모델 피처 자동 감지
    feature_cols = model.feature_name_
    df = df.dropna(subset=feature_cols)

    # 예측
    df['predict'] = model.predict(df[feature_cols])
    df['next_return'] = df.groupby('ticker')['Close'].shift(-1) / df['Close'] - 1

    # 전략:
    # 매수 신호(1) → 투자
    # 관망(0)/매도(2) → 현금 보유
    buy_df = df[df['predict'] == 1]
    daily_returns = (
        buy_df.groupby('date')['next_return'].mean() - 0.0015  # 수수료 차감
    )

    portfolio = pd.DataFrame(daily_returns).fillna(0).rename(
        columns={'next_return': 'daily_return'}
    )
    portfolio['cum_return'] = (1 + portfolio['daily_return']).cumprod()

    # 성과 지표
    total_return = (portfolio['cum_return'].iloc[-1] - 1) * 100
    mdd = ((portfolio['cum_return'] / portfolio['cum_return'].cummax()) - 1).min() * 100
    sharpe = (portfolio['daily_return'].mean() / portfolio['daily_return'].std()) * (252 ** 0.5)

    logger.info(f"\n=== 백테스트 결과 ===")
    logger.info(f"총 수익률: {total_return:.2f}%")
    logger.info(f"MDD: {mdd:.2f}%")
    logger.info(f"샤프비율: {sharpe:.2f}")
    logger.info(f"매수 신호 발생 횟수: {len(buy_df)}회")

    print(f"\n=== {sector} 백테스트 결과 ===")
    print(f"총 수익률: {total_return:.2f}%")
    print(f"MDD: {mdd:.2f}%")
    print(f"샤프비율: {sharpe:.2f}")

    # DB 저장
    conn = get_connection()
    portfolio.reset_index().to_sql(
        'backtest_results', conn, if_exists='replace', index=False
    )
    conn.close()
    logger.info("백테스트 결과 DB 저장 완료!")

    return portfolio

if __name__ == "__main__":
    run_backtest()