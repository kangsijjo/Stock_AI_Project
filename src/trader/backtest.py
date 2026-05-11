import pandas as pd
import numpy as np
import pickle
import os
from src.config_db import get_connection
from src.logger import get_logger

logger = get_logger('backtest')

# [수정된 부분] 기본값을 top_k=1 로 변경하여 1등 종목에 100% 집중 투자합니다.
def run_backtest(sector=None, market=None, top_k=1):
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

    logger.info(f"=== {sector} 실전 Top-{top_k} 집중 투자 백테스트 시작 ===")

    # 1. 모델 로드
    model_path = f'src/models/saved/{sector}_model.pkl'
    if not os.path.exists(model_path):
        logger.error(f"모델 없음: {model_path}")
        return

    with open(model_path, 'rb') as f:
        model = pickle.load(f)

    # 2. 지표 데이터 로드
    conn = get_connection()
    table = 'korea_indicators' if market == 'korea' else 'usa_indicators'
    try:
        df = pd.read_sql(
            f"SELECT * FROM {table} WHERE sector=? ORDER BY date, ticker",
            conn, params=[sector]
        )
    except Exception as e:
        logger.error(f"지표 데이터를 불러올 수 없습니다: {e}")
        conn.close()
        return
    conn.close()

    if len(df) == 0:
        logger.error("데이터 없음")
        return

    feature_cols = model.feature_name_
    df = df.dropna(subset=feature_cols)

    # 3. AI 예측 및 확률(Probability) 추출
    df['predict'] = model.predict(df[feature_cols])
    
    class_1_idx = list(model.classes_).index(1)
    df['buy_prob'] = model.predict_proba(df[feature_cols])[:, class_1_idx]

    df['next_return'] = df.groupby('ticker')['Close'].shift(-1) / df['Close'] - 1
    df = df.dropna(subset=['next_return'])

    # 4. 실전 100% 집중 투자 로직
    # top_k가 1이므로, 1위 종목에 자본금의 100% (weight = 1.0/1 = 1.0)가 투입됩니다.
    logger.info(f"매일 상승 확률(buy_prob)이 가장 높은 {top_k}위 종목에 자본금 100%를 집중 투자합니다.")
    
    buy_candidates = df[df['predict'] == 1]
    daily_portfolio = []
    
    for date, group in buy_candidates.groupby('date'):
        top_stocks = group.nlargest(top_k, 'buy_prob')
        weight = 1.0 / top_k
        
        day_return = ((top_stocks['next_return'] - 0.0015) * weight).sum()
        
        daily_portfolio.append({
            'date': date,
            'daily_return': day_return,
            'invested_count': len(top_stocks)
        })

    portfolio = pd.DataFrame(daily_portfolio)
    
    all_dates = pd.DataFrame({'date': df['date'].unique()})
    portfolio = pd.merge(all_dates, portfolio, on='date', how='left').fillna({'daily_return': 0, 'invested_count': 0})
    portfolio = portfolio.sort_values('date').reset_index(drop=True)
    
    # 5. 최종 누적 성과 계산
    portfolio['cum_return'] = (1 + portfolio['daily_return']).cumprod()

    total_return = (portfolio['cum_return'].iloc[-1] - 1) * 100
    
    roll_max = portfolio['cum_return'].cummax()
    drawdown = portfolio['cum_return'] / roll_max - 1.0
    mdd = drawdown.min() * 100
    
    mean_ret = portfolio['daily_return'].mean()
    std_ret = portfolio['daily_return'].std()
    sharpe = (mean_ret / std_ret) * np.sqrt(252) if std_ret > 0 else 0

    logger.info(f"\n=== 실전 집중투자 백테스트 결과 ===")
    logger.info(f"총 수익률: {total_return:.2f}%")
    logger.info(f"MDD: {mdd:.2f}%")
    logger.info(f"샤프비율: {sharpe:.2f}")

    print(f"\n=== {sector} 실전 Top-{top_k} 집중투자 백테스트 결과 ===")
    print(f"총 누적 수익률: {total_return:.2f}%")
    print(f"최대 낙폭(MDD): {mdd:.2f}%")
    print(f"샤프 비율: {sharpe:.2f}")

    # DB 저장
    conn = get_connection()
    portfolio.to_sql('backtest_results', conn, if_exists='replace', index=False)
    conn.close()
    logger.info("현실적인 집중투자 백테스트 결과 DB 저장 완료!")

    return portfolio

if __name__ == "__main__":
    run_backtest()