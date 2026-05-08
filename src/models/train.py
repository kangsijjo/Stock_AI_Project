import pandas as pd
import numpy as np
import sqlite3
import os
import lightgbm as lgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score
import pickle

DB_PATH = os.path.join(os.path.dirname(__file__), '../../data/stock.db')

def get_connection():
    return sqlite3.connect(DB_PATH)

def load_data(sector=None, market='korea'):
    """DB에서 데이터 로드"""
    conn = get_connection()
    table = 'korea_stocks' if market == 'korea' else 'usa_stocks'
    
    if sector:
        query = f"SELECT * FROM {table} WHERE sector=? ORDER BY ticker, date"
        df = pd.read_sql(query, conn, params=[sector])
    else:
        query = f"SELECT * FROM {table} ORDER BY ticker, date"
        df = pd.read_sql(query, conn)
    
    conn.close()
    return df

def make_features(df):
    """피처 생성 (기술지표 기반)"""
    df = df.copy()
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values(['ticker', 'date'])
    
    features = []
    
    for ticker, group in df.groupby('ticker'):
        g = group.copy()
        
        # 기본 피처
        g['return_1d'] = g['Close'].pct_change(1)
        g['return_5d'] = g['Close'].pct_change(5)
        g['return_20d'] = g['Close'].pct_change(20)
        
        # 이동평균
        g['ma5'] = g['Close'].rolling(5).mean()
        g['ma20'] = g['Close'].rolling(20).mean()
        g['ma60'] = g['Close'].rolling(60).mean()
        
        # 이동평균 대비 현재가
        g['ma5_ratio'] = g['Close'] / g['ma5']
        g['ma20_ratio'] = g['Close'] / g['ma20']
        g['ma60_ratio'] = g['Close'] / g['ma60']
        
        # RSI
        delta = g['Close'].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        g['rsi'] = 100 - (100 / (1 + gain / loss))
        
        # 거래량
        g['vol_ratio'] = g['Volume'] / g['Volume'].rolling(20).mean()
        
        # 변동성
        g['volatility'] = g['return_1d'].rolling(20).std()
        
        # 타겟: 5일 후 상승 여부 (1=상승, 0=하락)
        g['target'] = (g['Close'].shift(-5) > g['Close']).astype(int)
        
        features.append(g)
    
    result = pd.concat(features, ignore_index=True)
    return result

def train_model(sector=None, market=None):
    """LightGBM 모델 학습"""
    from src.collector.config import ACTIVE_SECTOR
    
    if sector is None:
        sector = ACTIVE_SECTOR
    
    print(f"\n=== {sector} 섹터 모델 학습 시작 ===")
    
    # 데이터 로드
    df = load_data(sector, market)
    if len(df) == 0:
        print("데이터 없음. 수집 먼저 완료해주세요.")
        return
    
    print(f"데이터 로드: {len(df)}행")
    
    # 피처 생성
    df = make_features(df)
    
    # 피처 컬럼 정의
    feature_cols = [
        'return_1d', 'return_5d', 'return_20d',
        'ma5_ratio', 'ma20_ratio', 'ma60_ratio',
        'rsi', 'vol_ratio', 'volatility'
    ]
    
    # 결측치 제거
    df = df.dropna(subset=feature_cols + ['target'])
    print(f"결측치 제거 후: {len(df)}행")
    
    X = df[feature_cols]
    y = df['target']
    
    # 시계열 분할 (미래 데이터로 학습하지 않도록)
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
    
    print(f"\n평균 정확도: {np.mean(scores):.4f}")
    
    # 전체 데이터로 최종 모델 학습
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
    print(f"\n모델 저장 완료: {model_path}")
    
    return final_model

if __name__ == "__main__":
    train_model()