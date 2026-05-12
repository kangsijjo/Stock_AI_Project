import sys
from unittest.mock import MagicMock

# 🚨 [방어막] FinRL의 불필요한 미국 API 로드 차단
sys.modules['alpaca_trade_api'] = MagicMock()
sys.modules['alpha_vantage'] = MagicMock()
sys.modules['alpha_vantage.sectorperformance'] = MagicMock()

import pandas as pd
import numpy as np
import os
from src.config_db import get_connection
from src.logger import get_logger

logger = get_logger('finrl')

# FinRL 필수 설정
INITIAL_AMOUNT = 10_000_000  # 초기 자금 1000만원
TRANSACTION_COST = 0.0035    # 수수료 0.35%
HMAX = 100                   # 최대 매수 주식 수

def prepare_finrl_data(sector=None, market='korea'):
    """DB에서 FinRL 형식 데이터 로드 및 결점 보완"""
    from src.collector.config import ACTIVE_SECTOR
    if sector is None:
        sector = ACTIVE_SECTOR

    conn = get_connection()
    table = 'finrl_dataset_kr' if market == 'korea' else 'finrl_dataset_us'

    df = pd.read_sql(
        f"SELECT * FROM {table} WHERE sector=? ORDER BY date, tic",
        conn, params=[sector]
    )
    conn.close()

    if df.empty:
        logger.warning(f"FinRL 데이터 없음 (스킵): {sector}")
        return None

    logger.info(f"[{sector}] FinRL 데이터 로드: {len(df)}행")

    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values(['date', 'tic']).reset_index(drop=True)

    # 실제로 존재하는 피처만 사용
    desired_tech_cols = [
        'ma5_ratio', 'ma20_ratio', 'ma60_ratio', 'return_1d', 'return_5d', 'return_20d',
        'rsi', 'vol_ratio', 'volatility', 'macd', 'macd_signal', 'macd_hist',
        'bb_upper', 'bb_lower', 'vol_spike', 'nasdaq_chg', 'sox_chg', 'krw_usd_chg',
        'vix_chg', 'kospi_chg', 'news_sentiment', 'lgbm_prob'
    ]
    tech_cols = [c for c in desired_tech_cols if c in df.columns]
    df = df.dropna(subset=tech_cols)

    # 개근 종목만 필터링 (FinRL 매트릭스 유지용)
    ticker_counts = df.groupby('tic').size()
    max_count = ticker_counts.max()
    valid_tickers = ticker_counts[ticker_counts == max_count].index
    df = df[df['tic'].isin(valid_tickers)].reset_index(drop=True)

    if df.empty or df['tic'].nunique() == 0:
        return None

    return df, tech_cols

def train_finrl(sector=None, market='korea'):
    """FinRL 강화학습 에이전트 학습"""
    from finrl.meta.env_stock_trading.env_stocktrading import StockTradingEnv
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import DummyVecEnv

    logger.info(f"▶ [{sector}] FinRL PPO 학습 프로세스 가동")
    
    result = prepare_finrl_data(sector, market)
    if result is None:
        return
    df, tech_cols = result

    # 학습/테스트 분리 (2024년 기준)
    train_df = df[df['date'] < '2024-01-01'].reset_index(drop=True)
    if train_df.empty:
        logger.warning(f"[{sector}] 학습 데이터가 부족하여 스킵합니다.")
        return

    stock_dim = train_df['tic'].nunique()
    state_space = 1 + 2 * stock_dim + len(tech_cols) * stock_dim

    env_kwargs = {
        'df': train_df,
        'stock_dim': stock_dim,
        'hmax': HMAX,
        'initial_amount': INITIAL_AMOUNT,
        'num_stock_shares': [0] * stock_dim,
        'buy_cost_pct': [TRANSACTION_COST] * stock_dim,
        'sell_cost_pct': [TRANSACTION_COST] * stock_dim,
        'reward_scaling': 1e-4,
        'state_space': state_space,
        'action_space': stock_dim,
        'tech_indicator_list': tech_cols,
    }

    try:
        env = StockTradingEnv(**env_kwargs)
        env_train = DummyVecEnv([lambda: env])

        model = PPO(
            'MlpPolicy',
            env_train,
            verbose=0, # 전 섹터 학습 시 로그 폭발 방지를 위해 0으로 설정
            learning_rate=0.0003,
            n_steps=2048,
            batch_size=64,
            n_epochs=10,
        )
        # 학습량 (10만 단계 -> 테스트 시 1~5만 정도로 줄여서 시간 단축 가능)
        model.learn(total_timesteps=50000) 

        os.makedirs('src/models/saved/finrl', exist_ok=True)
        model_path = f'src/models/saved/finrl/{sector}_ppo'
        model.save(model_path)
        logger.info(f"✅ [{sector}] 학습 완료 및 저장: {model_path}")

    except Exception as e:
        logger.error(f"❌ [{sector}] 학습 실패: {e}")

def test_finrl(sector=None, market='korea'):
    """에이전트 성능 테스트 (생략 가능하나 검증용으로 유지)"""
    # ... (기존 test_finrl 코드와 동일하되 sector 인자 활용) ...
    pass

if __name__ == "__main__":
    import sys
    from src.collector.config import KOREA_SECTORS, ACTIVE_SECTOR

    cmd = sys.argv[1] if len(sys.argv) > 1 else 'train'
    arg_sector = sys.argv[2] if len(sys.argv) > 2 else None

    if cmd == 'train':
        if arg_sector == 'all':
            logger.info("🚀 [전 섹터 일괄 학습] 모드를 시작합니다.")
            for s in KOREA_SECTORS:
                train_finrl(sector=s)
        else:
            # 특정 섹터 지정 혹은 기본 활성 섹터 학습
            target = arg_sector if arg_sector else ACTIVE_SECTOR
            train_finrl(sector=target)
            
    elif cmd == 'test':
        if arg_sector == 'all':
            for s in KOREA_SECTORS:
                test_finrl(sector=s)
        else:
            target = arg_sector if arg_sector else ACTIVE_SECTOR
            test_finrl(sector=target)