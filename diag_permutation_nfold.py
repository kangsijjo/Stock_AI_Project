"""
[추가 검증] N개 fold 에서 Permutation Test 반복 → 평균 GAP 계산.

단일 fold 의 분산(±2%p)을 줄여 더 robust 하게 leakage 판정.
- 시장 평균 (test fold 의 next_return 평균)
- 정상 학습 Top5% 평균
- Permutation Top5% 평균
- 진짜 알파 = 정상 - perm

실행: python diag_permutation_nfold.py
"""
import sqlite3
import pandas as pd
import numpy as np
import lightgbm as lgb

SECTOR        = '반도체'
TRAIN_WEEKS   = 104
TEST_WEEKS    = 1
HOLDING_DAYS  = 5
N_FOLDS       = 10   # 검증 fold 수
N_TRIALS      = 3    # fold 당 permutation 시도 수
TOP_PCT       = 0.05

np.random.seed(42)

print("=" * 60)
print(f"[N-Fold Permutation Test] {SECTOR}  (N={N_FOLDS}, trials={N_TRIALS})")
print("=" * 60)

conn = sqlite3.connect('data/stock.db')
df = pd.read_sql(
    "SELECT * FROM korea_indicators WHERE sector=? ORDER BY date, ticker",
    conn, params=[SECTOR]
)
conn.close()

if df.empty:
    print("데이터 없음")
    raise SystemExit(0)

df['date'] = pd.to_datetime(df['date'])

# entry/exit/target (backtest.py 와 동일)
g = df.sort_values(['ticker', 'date']).groupby('ticker', sort=False)
df['entry_price'] = g['Open'].shift(-1)
df['exit_price']  = g['Close'].shift(-HOLDING_DAYS)
df.loc[~(df['entry_price'] > 0), ['entry_price', 'exit_price']] = np.nan
df['next_return'] = df['exit_price'] / df['entry_price'] - 1
df.loc[df['next_return'].abs() > 0.15, 'next_return'] = np.nan
df['next_return'] = df['next_return'].replace([np.inf, -np.inf], np.nan)
df['target'] = 0
df.loc[df['next_return'] >= 0.02, 'target'] = 1
df.loc[df['next_return'] <= -0.02, 'target'] = 2
df = df.dropna(subset=['entry_price', 'exit_price', 'next_return', 'target'])

exclude_cols = ['date', 'ticker', 'name', 'sector', 'market',
                'target', 'next_return',
                'entry_price', 'exit_price',
                'Open', 'High', 'Low', 'Close', 'Volume', 'Adj Close']
feature_cols = [c for c in df.columns if c not in exclude_cols]
df = df.dropna(subset=feature_cols)

# N 개 fold 분포: 가용 기간을 균등 분할
max_date = df['date'].max()
min_date = df['date'].min()
earliest_train_end = min_date + pd.DateOffset(weeks=TRAIN_WEEKS)
total_weeks = (max_date - earliest_train_end).days // 7
if total_weeks < N_FOLDS:
    N_FOLDS = max(2, total_weeks - 1)
fold_step = max(total_weeks // N_FOLDS, 1)

print(f"가용 기간: {earliest_train_end.date()} ~ {max_date.date()}  "
      f"({total_weeks} 주, fold_step={fold_step})\n")

fold_results = []
for fold_idx in range(N_FOLDS):
    train_end = earliest_train_end + pd.DateOffset(weeks=fold_idx * fold_step)
    purge_cutoff = train_end - pd.tseries.offsets.BDay(HOLDING_DAYS)
    train_start = train_end - pd.DateOffset(weeks=TRAIN_WEEKS)
    test_end = train_end + pd.DateOffset(weeks=TEST_WEEKS)
    if test_end > max_date:
        continue

    train_df = df[(df['date'] >= train_start) & (df['date'] <= purge_cutoff)]
    test_df  = df[(df['date'] > train_end) & (df['date'] <= test_end)]
    if len(train_df) < 100 or len(test_df) < 20:
        continue

    X_train, y_train = train_df[feature_cols], train_df['target']
    X_test = test_df[feature_cols]
    market_avg = test_df['next_return'].mean() * 100
    n_top = max(int(len(test_df) * TOP_PCT), 1)

    # 정상 학습
    model = lgb.LGBMClassifier(
        n_estimators=100, learning_rate=0.05, max_depth=6,
        random_state=42, verbose=-1
    )
    model.fit(X_train, y_train)
    proba = model.predict_proba(X_test)
    class_1_idx = list(model.classes_).index(1) if 1 in model.classes_ else 0
    tdf = test_df.copy()
    tdf['lgbm_prob'] = proba[:, class_1_idx]
    normal_top = tdf.nlargest(n_top, 'lgbm_prob')['next_return'].mean() * 100

    # Permutation
    perm_results = []
    for trial in range(N_TRIALS):
        y_shuffled = pd.Series(
            np.random.permutation(y_train.values), index=y_train.index
        )
        model_perm = lgb.LGBMClassifier(
            n_estimators=100, learning_rate=0.05, max_depth=6,
            random_state=100 + trial + fold_idx * 100, verbose=-1
        )
        model_perm.fit(X_train, y_shuffled)
        proba_perm = model_perm.predict_proba(X_test)
        c1 = list(model_perm.classes_).index(1) if 1 in model_perm.classes_ else 0
        tdf_p = test_df.copy()
        tdf_p['lgbm_prob'] = proba_perm[:, c1]
        perm_top = tdf_p.nlargest(n_top, 'lgbm_prob')['next_return'].mean() * 100
        perm_results.append(perm_top)

    perm_mean = float(np.nanmean(perm_results))
    alpha = normal_top - perm_mean
    fold_results.append({
        'train_end': train_end.date(),
        'market_avg': market_avg,
        'normal_top': normal_top,
        'perm_mean':  perm_mean,
        'alpha':      alpha,
    })
    print(f"  fold[{fold_idx+1:>2}/{N_FOLDS}] {train_end.date()}  "
          f"시장={market_avg:+6.2f}%  정상={normal_top:+6.2f}%  "
          f"perm={perm_mean:+6.2f}%  α={alpha:+6.2f}%p")

# 종합 통계
if fold_results:
    r = pd.DataFrame(fold_results)
    print()
    print("=" * 60)
    print("[종합 평균]")
    print(f"  시장 평균:      {r['market_avg'].mean():+.2f}%  (std {r['market_avg'].std():.2f})")
    print(f"  정상 학습 평균: {r['normal_top'].mean():+.2f}%  (std {r['normal_top'].std():.2f})")
    print(f"  Perm 평균:      {r['perm_mean'].mean():+.2f}%  (std {r['perm_mean'].std():.2f})")
    print(f"  진짜 알파:      {r['alpha'].mean():+.2f}%p (std {r['alpha'].std():.2f})")
    print(f"  알파가 양수인 fold 비율: {(r['alpha'] > 0).mean()*100:.0f}%")
    print("=" * 60)
    print("\n해석:")
    print("  - Perm 평균이 시장 평균에 가깝다 → features 정상")
    print("  - 알파 평균 > +0.5%p 이고 alpha>0 비율이 70%+ 이면 진짜 시그널")
    print("  - alpha std 가 크다면 시장 레짐 의존 (강세장에서만 작동 등)")
else:
    print("유효한 fold 없음 - TRAIN_WEEKS 조정 필요")
