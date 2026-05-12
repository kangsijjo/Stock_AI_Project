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
    """DB에서 FinRL 형식 데이터 로드 + 전처리"""
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
        logger.error(f"FinRL 데이터 없음: {sector}")
        return None

    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values(['date', 'tic']).reset_index(drop=True)

    # 1. 실제 존재하는 컬럼만 피처로 사용
    exclude_cols = [
        'date', 'tic', 'ticker', 'name', 'sector', 'market',
        'target', 'next_return', 'lgbm_pred',
        'Open', 'High', 'Low', 'Close', 'Volume',
        'open', 'high', 'low', 'close', 'volume',
        'Change', 'vol_ma20'
    ]
    tech_cols = [
        c for c in df.columns
        if c not in exclude_cols and df[c].dtype in ['float64', 'int64']
    ]
    logger.info(f"사용할 피처: {len(tech_cols)}개 → {tech_cols}")

    # 2. 결측치 제거 (존재하는 컬럼만)
    df = df.dropna(subset=tech_cols)

    # 3. FinRL 결벽증 해결 - 모든 날짜에 동일 종목 수 맞추기
    # 전체 기간 중 매일 거래된 종목만 선택
    date_counts = df.groupby('date')['tic'].count()
    full_trading_days = date_counts[date_counts == date_counts.max()].index
    df = df[df['date'].isin(full_trading_days)]

    # 매일 등장하는 종목만 선택
    total_days = df['date'].nunique()
    tic_counts = df.groupby('tic')['date'].count()
    valid_tickers = tic_counts[tic_counts == total_days].index
    df = df[df['tic'].isin(valid_tickers)].reset_index(drop=True)

    logger.info(f"전처리 완료: {len(df)}행 / {df['tic'].nunique()}개 종목 / {df['date'].nunique()}일")

    return df, tech_cols

def train_finrl(sector=None, market='korea'):
    """FinRL 강화학습 에이전트 학습"""
    from finrl.meta.env_stock_trading.env_stocktrading import StockTradingEnv
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import DummyVecEnv

    result = prepare_finrl_data(sector, market)
    if result is None:
        return
    df, tech_cols = result

    # 학습/테스트 분리
    train_df = df[df['date'] < '2024-01-01'].reset_index(drop=True)
    test_df  = df[df['date'] >= '2024-01-01'].reset_index(drop=True)

    logger.info(f"학습: {train_df['date'].min().date()} ~ {train_df['date'].max().date()}")
    logger.info(f"테스트: {test_df['date'].min().date()} ~ {test_df['date'].max().date()}")

    stock_dim = train_df['tic'].nunique()
    state_space = 1 + 2 * stock_dim + len(tech_cols) * stock_dim

    logger.info(f"종목 수: {stock_dim} / 상태 공간: {state_space}")

    # 환경 생성
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

        logger.info("PPO 에이전트 학습 시작...")
        model = PPO(
            'MlpPolicy',
            env_train,
            verbose=1,
            learning_rate=0.0003,
            n_steps=2048,
            batch_size=64,
            n_epochs=10,
        )
        model.learn(total_timesteps=100_000)

        # 모델 저장
        os.makedirs('src/models/saved/finrl', exist_ok=True)
        model_path = f'src/models/saved/finrl/{sector}_ppo'
        model.save(model_path)
        logger.info(f"FinRL 모델 저장 완료: {model_path}")

        return model, test_df, env_kwargs, tech_cols

    except Exception as e:
        logger.error(f"FinRL 학습 실패: {e}", exc_info=True)
        return None

def test_finrl(sector=None, market='korea'):
    """FinRL 에이전트 테스트"""
    from finrl.meta.env_stock_trading.env_stocktrading import StockTradingEnv
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import DummyVecEnv

    from src.collector.config import ACTIVE_SECTOR
    if sector is None:
        sector = ACTIVE_SECTOR

    model_path = f'src/models/saved/finrl/{sector}_ppo.zip'
    if not os.path.exists(model_path):
        logger.error(f"FinRL 모델 없음: {model_path}. 먼저 train_finrl() 실행")
        return

    result = prepare_finrl_data(sector, market)
    if result is None:
        return
    df, tech_cols = result

    test_df = df[df['date'] >= '2024-01-01'].reset_index(drop=True)
    stock_dim = test_df['tic'].nunique()
    state_space = 1 + 2 * stock_dim + len(tech_cols) * stock_dim

    env_kwargs = {
        'df': test_df,
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

    model = PPO.load(model_path)
    env = StockTradingEnv(**env_kwargs)
    env_test = DummyVecEnv([lambda: env])

    obs = env_test.reset()
    done = False
    while not done:
        action, _ = model.predict(obs)
        obs, reward, done, info = env_test.step(action)

    # 결과 추출
    asset_memory = env.asset_memory
    portfolio = pd.DataFrame({
        'date': test_df['date'].unique()[:len(asset_memory)],
        'total_asset': asset_memory
    })
    portfolio['daily_return'] = portfolio['total_asset'].pct_change().fillna(0)
    portfolio['cum_return'] = portfolio['total_asset'] / INITIAL_AMOUNT

    total_return = (portfolio['cum_return'].iloc[-1] - 1) * 100
    mdd = (portfolio['cum_return'] / portfolio['cum_return'].cummax() - 1).min() * 100
    std = portfolio['daily_return'].std()
    sharpe = (portfolio['daily_return'].mean() / std * np.sqrt(252)) if std > 0 else 0

    logger.info(f"\n=== FinRL PPO 테스트 결과 ===")
    logger.info(f"총 수익률: {total_return:.2f}%")
    logger.info(f"MDD: {mdd:.2f}%")
    logger.info(f"샤프비율: {sharpe:.2f}")

    print(f"\n=== [{sector}] FinRL PPO 백테스트 결과 ===")
    print(f"총 수익률: {total_return:.2f}%")
    print(f"MDD: {mdd:.2f}%")
    print(f"샤프비율: {sharpe:.2f}")

    return portfolio

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'train'

    if cmd == 'train':
        train_finrl()
    elif cmd == 'test':
        test_finrl()