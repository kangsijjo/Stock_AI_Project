import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score
import pickle
import os
from src.config_db import get_connection
from src.logger import get_logger
from src.processor.indicators import add_indicators, FEATURE_COLS

logger = get_logger('train')

def load_data(sector, market='korea'):
    """DB에서 데이터 로드"""
    conn = get_connection()
    table = 'korea_stocks' if market == 'korea' else 'usa_stocks'
    df = pd.read_sql(
        f"SELECT * FROM {table} WHERE sector=? ORDER BY ticker, date",
        conn, params=[sector]
    )
    conn.close()
    return df

def load_macro():
    """거시지표 로드"""
    conn = get_connection()
    try:
        df = pd.read_sql("SELECT * FROM macro_indicators", conn)
        conn.close()
        return df
    except:
        conn.close()
        return pd.DataFrame()

def load_news(sector, market='korea'):
    """뉴스 감성 로드"""
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

def train_model(sector=None, market=None):
    """LightGBM 모델 학습"""
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

    logger.info(f"=== {sector} 섹터 모델 학습 시작 ===")

    # 데이터 로드
    df = load_data(sector, market)
    if len(df) == 0:
        logger.warning("데이터 없음. 수집 먼저 완료해주세요.")
        return

    logger.info(f"데이터 로드: {len(df)}행")

    # 거시지표 + 뉴스 로드
    macro_df = load_macro()
    news_df  = load_news(sector, market)

    if not news_df.empty:
        logger.info(f"뉴스 데이터 로드: {len(news_df)}개 (가중치: {NEWS_WEIGHT})")
    else:
        logger.info("뉴스 데이터 없음 - 기술지표 + 거시지표만 사용")

    # indicators.py의 add_indicators로 피처 생성
    logger.info("피처 생성 중...")
    features = []
    for ticker, group in df.groupby('ticker'):
        g = group.copy()
        g = add_indicators(g, macro_df, news_df, NEWS_WEIGHT)

        # 3분류 레이블
        future_return = (g['Close'].shift(-5) - g['Close']) / g['Close']
        g['target'] = 0
        g.loc[future_return >= 0.02, 'target'] = 1
        g.loc[future_return <= -0.02, 'target'] = 2

        features.append(g)

    df = pd.concat(features, ignore_index=True)

    # 결측치 제거
    df = df.dropna(subset=FEATURE_COLS + ['target'])
    logger.info(f"결측치 제거 후: {len(df)}행")
    logger.info(f"매수(1): {(df['target']==1).sum()}개 / "
               f"관망(0): {(df['target']==0).sum()}개 / "
               f"매도(2): {(df['target']==2).sum()}개")

    X = df[FEATURE_COLS]
    y = df['target']

    # 시계열 분할 학습
    tscv = TimeSeriesSplit(n_splits=5)
    scores = []

    for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
        X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
        y_train, y_val = y.iloc[train_idx], y.iloc[val_idx]

        model = lgb.LGBMClassifier(
            n_estimators=100,
            learning_rate=0.05,
            max_depth=6,
            num_leaves=31,
            random_state=42,
            verbose=-1
        )
        model.fit(X_train, y_train)
        pred = model.predict(X_val)
        score = accuracy_score(y_val, pred)
        scores.append(score)
        logger.info(f"  Fold {fold+1} 정확도: {score:.4f}")

    avg_score = np.mean(scores)
    logger.info(f"평균 정확도: {avg_score:.4f}")

    # 최종 모델 학습
    final_model = lgb.LGBMClassifier(
        n_estimators=100,
        learning_rate=0.05,
        max_depth=6,
        num_leaves=31,
        random_state=42,
        verbose=-1
    )
    final_model.fit(X, y)

    # 모델 저장
    os.makedirs('src/models/saved', exist_ok=True)
    model_path = f'src/models/saved/{sector}_model.pkl'
    with open(model_path, 'wb') as f:
        pickle.dump(final_model, f)
    logger.info(f"모델 저장 완료: {model_path}")

    return final_model

if __name__ == "__main__":
    train_model()