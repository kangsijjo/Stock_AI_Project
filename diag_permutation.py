"""
[진단 3] Permutation Test — leakage 의 결정적 증거를 찾는 표준 방법.

원리:
  features 와 target 의 매칭만 무작위로 깨뜨림(target shuffle).
  - features 가 정상이라면 모델이 학습할 신호가 없어야 함
    → 매수 시그널의 평균 수익률은 시장 평균(0 근처) 이어야 함
  - 만약 매수 시그널 평균이 양수로 유지된다면 features 자체에
    미래 정보가 섞여 있다는 결정적 증거 (leakage)

테스트 구간: 백테스트 가장 최근 1주 (한 fold)
실행 시간: 5~10분
"""
import sqlite3
import pandas as pd
import numpy as np
import lightgbm as lgb

SECTOR       = '반도체'
TRAIN_WEEKS  = 104
TEST_WEEKS   = 1
HOLDING_DAYS = 5
N_TRIALS     = 5
TOP_PCT      = 0.05   # 상위 5% 종목으로 평가 (시그널 강도 robust 비교)

np.random.seed(42)

print("=" * 60)
print(f"[진단 3] Permutation Test — [{SECTOR}]")
print("=" * 60)

conn = sqlite3.connect('data/stock.db')
df = pd.read_sql(
    "SELECT * FROM korea_indicators WHERE sector=? ORDER BY date, ticker",
    conn, params=[SECTOR]
)
conn.close()

if df.empty:
    print(f"[{SECTOR}] 데이터 없음 - indicators 먼저 실행")
    raise SystemExit(0)

df['date'] = pd.to_datetime(df['date'])

# entry/exit/target 계산 (backtest.py 와 동일)
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

# 가장 최근 1주를 test, 그 직전 104주를 train (purge 5BDay)
max_date = df['date'].max()
train_end = max_date - pd.DateOffset(weeks=TEST_WEEKS) - pd.Timedelta(days=1)
purge_cutoff = train_end - pd.tseries.offsets.BDay(HOLDING_DAYS)
train_start = train_end - pd.DateOffset(weeks=TRAIN_WEEKS)
test_end = train_end + pd.DateOffset(weeks=TEST_WEEKS)

train_df = df[(df['date'] >= train_start) & (df['date'] <= purge_cutoff)]
test_df  = df[(df['date'] > train_end) & (df['date'] <= test_end)]

print(f"train: {train_df['date'].min().date()} ~ {train_df['date'].max().date()} ({len(train_df)}행)")
print(f"test : {test_df['date'].min().date()} ~ {test_df['date'].max().date()} ({len(test_df)}행)")
print(f"features 수: {len(feature_cols)}")

if len(train_df) < 100 or len(test_df) == 0:
    print("⚠ 데이터 부족")
    raise SystemExit(0)

X_train, y_train = train_df[feature_cols], train_df['target']
X_test = test_df[feature_cols]


def evaluate(model, label):
    proba = model.predict_proba(X_test)
    class_1_idx = list(model.classes_).index(1) if 1 in model.classes_ else 0
    tdf = test_df.copy()
    tdf['lgbm_prob'] = proba[:, class_1_idx]
    # 상위 N% 종목의 next_return 평균 (lgbm_prob 분포에 robust)
    n_top = max(int(len(tdf) * TOP_PCT), 1)
    top = tdf.nlargest(n_top, 'lgbm_prob')
    mean_top = top['next_return'].mean() * 100
    # 0.55 이상 매수 시그널
    buy = tdf[tdf['lgbm_prob'] >= 0.55]
    mean_buy = buy['next_return'].mean() * 100 if len(buy) > 0 else float('nan')
    print(f"  [{label}] Top{int(TOP_PCT*100)}% (n={n_top}): {mean_top:+.2f}%  "
          f"| prob≥0.55 (n={len(buy)}): {mean_buy:+.2f}%")
    return mean_top


# ─── 정상 학습 (control) ───
print("\n[정상 학습]")
model_normal = lgb.LGBMClassifier(
    n_estimators=100, learning_rate=0.05, max_depth=6,
    random_state=42, verbose=-1
)
model_normal.fit(X_train, y_train)
normal_top = evaluate(model_normal, "정상")

# ─── Permutation: target shuffle ───
print("\n[Permutation: target 무작위 셔플]")
perm_tops = []
for trial in range(N_TRIALS):
    y_shuffled = pd.Series(
        np.random.permutation(y_train.values), index=y_train.index
    )
    model = lgb.LGBMClassifier(
        n_estimators=100, learning_rate=0.05, max_depth=6,
        random_state=100 + trial, verbose=-1
    )
    model.fit(X_train, y_shuffled)
    mean_top = evaluate(model, f"trial {trial+1}")
    perm_tops.append(mean_top)

perm_mean = np.nanmean(perm_tops)

print("\n" + "=" * 60)
print("[종합 판정]")
print(f"  정상 학습:      Top5% 평균 = {normal_top:+.2f}%")
print(f"  Permutation:    Top5% 평균 = {perm_mean:+.2f}%  (5회 평균)")
print(f"  GAP (정상 - perm):           {normal_top - perm_mean:+.2f}%p")
print("=" * 60)
print("\n해석:")
print("  - perm 결과 평균이 -0.5% ~ +0.5% 근처이면 features 정상")
print("    (모델이 random target 으로는 학습 불가 → 시장 평균 근처)")
print("  - perm 결과 평균이 +1% 이상이면 features 에 leakage 존재")
print("    (target 이 random 인데도 top 종목이 양수 → features 자체가 미래 봄)")
print(f"  - 정상 결과({normal_top:+.2f}%) - perm({perm_mean:+.2f}%) = 진짜 알파의 크기")
