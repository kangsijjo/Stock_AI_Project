import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score
import pickle
import os
from src.config_db import get_connection
from src.logger import get_logger
from src.processor.indicators import FEATURE_COLS

logger = get_logger('train')

def load_data(sector, market='korea'):
    """DB에서 데이터 로드 (지표가 이미 계산된 indicators 테이블 전용 사용)"""
    conn = get_connection()
    table = 'korea_indicators' if market == 'korea' else 'usa_indicators'
    try:
        df = pd.read_sql(
            f"SELECT * FROM {table} WHERE sector=? ORDER BY ticker, date",
            conn, params=[sector]
        )
    except Exception as e:
        logger.error(f"[{table}] 테이블을 찾을 수 없습니다. 파이프라인에서 지표 생성을 먼저 진행해주세요.")
        df = pd.DataFrame()
    conn.close()
    return df

def train_model(sector=None, market=None):
    from src.collector.config import ACTIVE_SECTOR

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

    df = load_data(sector, market)
    if len(df) == 0:
        logger.warning("데이터 없음. 수집 및 지표생성을 먼저 완료해주세요.")
        return

    logger.info(f"데이터 로드: {len(df)}행 (21개 피처 포함)")

    # 보스께서 작성하신 3분류 타겟 생성 로직 완벽 보존
    features = []
    for ticker, group in df.groupby('ticker'):
        g = group.copy()
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

    # 보스께서 공들여 세팅하신 시계열 분할 학습 및 하이퍼파라미터 완벽 복구
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

# src/models/train.py 맨 아래 덮어씌울 부분
if __name__ == "__main__":
    import sys
    from src.collector.config import ACTIVE_SECTOR, KOREA_SECTORS
    
    # 터미널 인자가 있는지 확인
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == 'all':
            logger.info("🚀 전 섹터 일괄 학습 모드 가동")
            for s in KOREA_SECTORS:
                train_model(s)
        else:
            # 특정 섹터 지정 실행
            train_model(cmd)
    else:
        # 인자가 없으면 자동화 모드 작동
        logger.info(f"🤖 자동화 모드: 현재 활성 섹터[{ACTIVE_SECTOR}] 학습 진행")
        train_model(ACTIVE_SECTOR)