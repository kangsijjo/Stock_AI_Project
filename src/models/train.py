import pandas as pd
import numpy as np
import sqlite3
import os
import lightgbm as lgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score
import pickle

from src.config_db import get_db_path
DB_PATH = get_db_path()

def get_connection():
    return sqlite3.connect(DB_PATH)

def load_data(sector=None, market='korea'):
    conn = get_connection()
    table = 'korea_stocks' if market == 'korea' else 'usa_stocks'
    if sector:
        df = pd.read_sql(f"SELECT * FROM {table} WHERE sector=? ORDER BY ticker, date", conn, params=[sector])
    else:
        df = pd.read_sql(f"SELECT * FROM {table} ORDER BY ticker, date", conn)
    conn.close()
    return df

def load_news_sentiment(sector, market):
    """뉴스 감성 점수 로드 - 날짜별 평균"""
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

def make_features(df, news_df=None, news_weight=0.5):
    """피처 생성 (기술지표 + 뉴스 감성)"""
    df = df.copy()
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values(['ticker', 'date'])

    features = []

    for ticker, group in df.groupby('ticker'):
        g = group.copy()

        g['return_1d'] = g['Close'].pct_change(1)
        g['return_5d'] = g['Close'].pct_change(5)
        g['return_20d'] = g['Close'].pct_change(20)

        g['ma5'] = g['Close'].rolling(5).mean()
        g['ma20'] = g['Close'].rolling(20).mean()
        g['ma60'] = g['Close'].rolling(60).mean()

        g['ma5_ratio'] = g['Close'] / g['ma5']
        g['ma20_ratio'] = g['Close'] / g['ma20']
        g['ma60_ratio'] = g['Close'] / g['ma60']

        delta = g['Close'].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        g['rsi'] = 100 - (100 / (1 + gain / loss))

        g['vol_ratio'] = g['Volume'] / g['Volume'].rolling(20).mean()
        g['volatility'] = g['return_1d'].rolling(20).std()

        # 뉴스 감성 점수 추가
        g['news_sentiment'] = 0.0
        if news_df is not None and not news_df.empty:
            ticker_news = news_df[news_df['ticker'] == ticker].copy()
            if not ticker_news.empty:
                try:
                    ticker_news['pubDate'] = pd.to_datetime(ticker_news['pubDate'], errors='coerce')
                    ticker_news = ticker_news.dropna(subset=['pubDate'])
                    ticker_news['date'] = ticker_news['pubDate'].dt.date
                    daily_sentiment = ticker_news.groupby('date')['sentiment'].mean()
                    g['date_only'] = g['date'].dt.date
                    g['news_sentiment'] = g['date_only'].map(daily_sentiment).fillna(0.0)
                    g['news_sentiment'] = g['news_sentiment'] * news_weight
                    g = g.drop('date_only', axis=1)
                except:
                    g['news_sentiment'] = 0.0

        g['target'] = (g['Close'].shift(-5) > g['Close']).astype(int)
        features.append(g)

    return pd.concat(features, ignore_index=True)

def train_model(sector=None, market=None):
    from src.collector.config import ACTIVE_SECTOR, NEWS_WEIGHT

    if sector is None:
        sector = ACTIVE_SECTOR

    if market is None:
        usa_sectors = ['Industrials', 'Financials', 'Information Technology',
                       'Health Care', 'Consumer Discretionary', 'Consumer Staples',
                       'Utilities', 'Real Estate', 'Materials',
                       'Communication Services', 'Energy']
        market = 'usa' if sector in usa_sectors else 'korea'

    print(f"\n=== {sector} 섹터 모델 학습 시작 ===")

    df = load_data(sector, market)
    if len(df) == 0:
        print("데이터 없음. 수집 먼저 완료해주세요.")
        return

    print(f"데이터 로드: {len(df)}행")

    # 뉴스 감성 로드
    news_df = load_news_sentiment(sector, market)
    if not news_df.empty:
        print(f"뉴스 데이터 로드: {len(news_df)}개 (가중치: {NEWS_WEIGHT})")
    else:
        print("뉴스 데이터 없음 - 기술지표만 사용")

    df = make_features(df, news_df, NEWS_WEIGHT)

    # 뉴스 있으면 피처에 추가
    feature_cols = [
        'return_1d', 'return_5d', 'return_20d',
        'ma5_ratio', 'ma20_ratio', 'ma60_ratio',
        'rsi', 'vol_ratio', 'volatility'
    ]
    if not news_df.empty:
        feature_cols.append('news_sentiment')
        print("뉴스 감성 피처 추가됨")

    df = df.dropna(subset=feature_cols + ['target'])
    print(f"결측치 제거 후: {len(df)}행")

    X = df[feature_cols]
    y = df['target']

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
        print(f"  Fold {fold+1} 정확도: {score:.4f}")

    avg_score = np.mean(scores)
    print(f"\n평균 정확도: {avg_score:.4f}")

    # 뉴스 가중치 자동 조정
    if not news_df.empty and avg_score < 0.52:
        new_weight = max(0.0, NEWS_WEIGHT - 0.1)
        print(f"뉴스 효과 낮음 → 가중치 자동 조정: {NEWS_WEIGHT} → {new_weight}")
        update_news_weight(new_weight)
    elif not news_df.empty and avg_score > 0.57:
        new_weight = min(1.0, NEWS_WEIGHT + 0.1)
        print(f"뉴스 효과 좋음 → 가중치 자동 조정: {NEWS_WEIGHT} → {new_weight}")
        update_news_weight(new_weight)

    final_model = lgb.LGBMClassifier(
        n_estimators=100,
        learning_rate=0.05,
        max_depth=6,
        num_leaves=31,
        random_state=42,
        verbose=-1
    )
    final_model.fit(X, y)

    os.makedirs('src/models/saved', exist_ok=True)
    model_path = f'src/models/saved/{sector}_model.pkl'
    with open(model_path, 'wb') as f:
        pickle.dump(final_model, f)
    print(f"\n모델 저장 완료: {model_path}")

    return final_model

def update_news_weight(new_weight):
    """config.py NEWS_WEIGHT 자동 업데이트"""
    config_path = 'src/collector/config.py'
    with open(config_path, 'r', encoding='utf-8') as f:
        content = f.read()
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if line.startswith('NEWS_WEIGHT'):
            lines[i] = f'NEWS_WEIGHT = {new_weight}'
            break
    with open(config_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

if __name__ == "__main__":
    train_model()