import pandas as pd
import numpy as np
import lightgbm as lgb
from tqdm import tqdm
from src.config_db import get_connection
from src.logger import get_logger

logger = get_logger('walk_forward')

def run_walk_forward_backtest(sector=None, market=None, train_weeks=104, test_weeks=1):
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

    conn = get_connection()
    table = 'korea_indicators' if market == 'korea' else 'usa_indicators'
    finrl_table = 'finrl_dataset_kr' if market == 'korea' else 'finrl_dataset_us'

    logger.info(f"=== [{sector}] 주간 Walk-Forward (증분 업데이트 모드) 시작 ===")

    # 1. 기존 DB 확인 (내일부터는 여기서 건너뛰기가 작동함)
    last_saved_date = None
    try:
        res = pd.read_sql(f"SELECT MAX(date) as max_date FROM {finrl_table} WHERE sector=?", conn, params=[sector])
        if not res.empty and res['max_date'].iloc[0] is not None:
            last_saved_date = pd.to_datetime(res['max_date'].iloc[0])
            logger.info(f"📍 DB 확인 완료: {last_saved_date.date()} 까지 이미 학습/저장되어 있습니다.")
    except:
        pass 

    # 2. 지표 데이터 로드
    try:
        df = pd.read_sql(f"SELECT * FROM {table} WHERE sector=? ORDER BY date, ticker", conn, params=[sector])
    except Exception as e:
        logger.error(f"데이터 로드 실패: {e}")
        conn.close()
        return

    if df.empty:
        conn.close()
        return

    df['date'] = pd.to_datetime(df['date'])

    # 타겟 생성
    df['next_return'] = df.groupby('ticker')['Close'].shift(-1) / df['Close'] - 1
    future_return = df.groupby('ticker')['Close'].pct_change(5).shift(-5)
    df['target'] = 0
    df.loc[future_return >= 0.02, 'target'] = 1
    df.loc[future_return <= -0.02, 'target'] = 2
    df = df.dropna(subset=['next_return', 'target'])

    # 피처 컬럼 식별
    exclude_cols = ['date', 'ticker', 'name', 'sector', 'market', 'target', 'next_return', 'Open', 'High', 'Low', 'Close', 'Volume', 'Adj Close']
    feature_cols = [c for c in df.columns if c not in exclude_cols]
    df = df.dropna(subset=feature_cols)

    if df.empty:
        logger.warning(f"[{sector}] 유효한 지표 데이터가 부족하여 스킵합니다.")
        return pd.DataFrame()

    min_date = df['date'].min()
    max_date = df['date'].max()

    if pd.isna(min_date) or pd.isna(max_date):
        return pd.DataFrame()

    total_days = (max_date - min_date).days
    total_windows = max(1, (total_days // 7) - train_weeks)

    finrl_data_list = []
    current_train_start = min_date

    # 3. Walk-Forward 핵심 루프 (주 단위)
    with tqdm(total=total_windows, desc="주간 Walk-Forward", unit="주") as pbar:
        while True:
            current_train_end = current_train_start + pd.DateOffset(weeks=train_weeks) - pd.Timedelta(days=1)
            current_test_end = current_train_end + pd.DateOffset(weeks=test_weeks)

            if current_train_end >= max_date:
                break

            # 💡 증분 업데이트: 기존에 했던 기간이면 고속 스킵!
            if last_saved_date is not None and current_test_end <= last_saved_date:
                current_train_start += pd.DateOffset(weeks=test_weeks)
                pbar.update(1)
                continue

            train_df = df[(df['date'] >= current_train_start) & (df['date'] <= current_train_end)]
            test_df = df[(df['date'] > current_train_end) & (df['date'] <= current_test_end)]

            # 테스트 구간이 기존과 일부 겹치면 새로운 날짜만 남기기
            if last_saved_date is not None:
                test_df = test_df[test_df['date'] > last_saved_date]

            if len(train_df) > 100 and len(test_df) > 0:
                X_train, y_train = train_df[feature_cols], train_df['target']
                X_test = test_df[feature_cols]

                model = lgb.LGBMClassifier(n_estimators=100, learning_rate=0.05, max_depth=6, random_state=42, verbose=-1)
                model.fit(X_train, y_train)

                test_df_copy = test_df.copy()
                class_1_idx = list(model.classes_).index(1) if 1 in model.classes_ else 0
                test_df_copy['lgbm_prob'] = model.predict_proba(X_test)[:, class_1_idx]
                test_df_copy['lgbm_pred'] = model.predict(X_test)

                finrl_data_list.append(test_df_copy)

            current_train_start += pd.DateOffset(weeks=test_weeks)
            pbar.update(1)

    # 4. 신규 데이터 이어 붙이기 (Append)
    if finrl_data_list:
        final_df = pd.concat(finrl_data_list, ignore_index=True)
        finrl_df = final_df.copy()
        finrl_df = finrl_df.rename(columns={'ticker': 'tic', 'Close': 'close', 'Open': 'open', 'High': 'high', 'Low': 'low', 'Volume': 'volume'})
        finrl_df['date'] = finrl_df['date'].dt.strftime('%Y-%m-%d')
        finrl_df.to_sql(finrl_table, conn, if_exists='append', index=False)
        conn.commit()
        logger.info(f"✨ 신규 데이터 {len(finrl_df)}행 DB 추가 완료!")
    else:
        logger.info("✔️ 이미 모든 백테스트 데이터가 최신 상태입니다. (신규 학습 스킵)")

    # 5. 수수료 방어 로직 반영 누적 성과 계산
    logger.info("=== 전체 기간 누적 성과 계산 (종목 변경 시에만 수수료 0.35% 부과) ===")
    full_df = pd.read_sql(f"SELECT * FROM {finrl_table} WHERE sector=?", conn, params=[sector])
    conn.close()

    if full_df.empty:
        return pd.DataFrame()

    full_df['date'] = pd.to_datetime(full_df['date'])
    
    daily_portfolio = []
    current_holding_ticker = None

    for date, group in full_df.groupby('date'):
        top_stock = group.nlargest(1, 'lgbm_prob')
        
        if not top_stock.empty and float(top_stock.iloc[0]['lgbm_prob']) >= 0.5:
            best_ticker = top_stock.iloc[0]['tic']
            day_return = float(top_stock.iloc[0]['next_return'])
            
            # 수수료 방어: 종목이 바뀔 때만 수수료 0.35% 차감
            if current_holding_ticker != best_ticker:
                day_return -= 0.0035
                current_holding_ticker = best_ticker
        else:
            day_return = 0.0 
            if current_holding_ticker is not None:
                current_holding_ticker = None
                
        daily_portfolio.append({'date': date, 'daily_return': day_return})

    portfolio = pd.DataFrame(daily_portfolio).sort_values('date')
    portfolio['cum_return'] = (1 + portfolio['daily_return']).cumprod()

    total_return = (portfolio['cum_return'].iloc[-1] - 1) * 100
    mdd = (portfolio['cum_return'] / portfolio['cum_return'].cummax() - 1).min() * 100
    std = portfolio['daily_return'].std()
    sharpe = (portfolio['daily_return'].mean() / std * np.sqrt(252)) if std > 0 else 0

    print(f"\n=== [{sector}] 실전 검증 완료 ===")
    print(f"총 수익률: {total_return:.2f}% | MDD: {mdd:.2f}% | 샤프비율: {sharpe:.2f}")

    return portfolio

if __name__ == "__main__":
    import sys
    from src.collector.config import ACTIVE_SECTOR, KOREA_SECTORS
    
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == 'all':
            logger.info("🚀 전 섹터 주간 Walk-Forward 백테스트 가동")
            for s in KOREA_SECTORS:
                run_walk_forward_backtest(sector=s)
        else:
            run_walk_forward_backtest(sector=cmd)
    else:
        run_walk_forward_backtest(sector=ACTIVE_SECTOR)