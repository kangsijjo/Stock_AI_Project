"""
[진단 1] pandas-ta-classic 의 SMA/RSI/볼린저 가 backward only 인지 직접 검증.

방법: 라이브러리 결과와 순수 pandas 구현(backward only)을 값으로 비교.
"""
import sqlite3
import pandas as pd
import numpy as np
import pandas_ta_classic as ta

conn = sqlite3.connect('data/stock.db')
df = pd.read_sql(
    "SELECT date, Close, Volume FROM korea_stocks WHERE ticker='005930' ORDER BY date",
    conn
).head(200)
conn.close()

df['date'] = pd.to_datetime(df['date'])
df = df.sort_values('date').reset_index(drop=True)

print("=" * 60)
print("[진단 1] pandas-ta-classic 직접 검증 (005930 처음 200일)")
print("=" * 60)

# ───────── SMA(5) ─────────
df['ta_sma5'] = ta.sma(df['Close'], length=5)
df['my_sma5'] = df['Close'].rolling(5).mean()
diff = (df['ta_sma5'] - df['my_sma5']).abs().dropna()
print(f"\n[SMA(5)] 라이브러리 vs backward rolling")
print(f"  max diff: {diff.max():.6f}")
if diff.max() < 0.0001:
    print("  ✓ backward only (정상)")
else:
    print("  ⚠ 라이브러리가 다른 방식! 확인 필요")
    print(df[['date', 'Close', 'ta_sma5', 'my_sma5']].head(10).to_string(index=False))

# ───────── SMA(20) ─────────
df['ta_sma20'] = ta.sma(df['Close'], length=20)
df['my_sma20'] = df['Close'].rolling(20).mean()
diff = (df['ta_sma20'] - df['my_sma20']).abs().dropna()
print(f"\n[SMA(20)] max diff: {diff.max():.6f}  ", end="")
print("✓" if diff.max() < 0.0001 else "⚠ 라이브러리가 다른 방식")

# ───────── RSI(14) ─────────
df['ta_rsi'] = ta.rsi(df['Close'], length=14)
# RSI 는 Wilder smoothing 이 표준 → backward only
delta = df['Close'].diff()
gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
df['my_rsi'] = 100 - (100 / (1 + gain / loss))
diff = (df['ta_rsi'] - df['my_rsi']).abs().dropna()
print(f"\n[RSI(14)] max diff (Wilder vs Wilder): {diff.max():.4f}  ", end="")
print("✓" if diff.max() < 1.0 else "⚠ 큰 차이")

# ───────── BBands(20) — upper/lower 라벨 검증 ─────────
print("\n[BBands(20)] 컬럼 순서 + 라벨 검증")
bb = ta.bbands(df['Close'], length=20)
print(f"  반환 컬럼: {list(bb.columns)}")
last_idx = bb.dropna().index[-1]
close_val = df['Close'].iloc[last_idx]
print(f"  마지막 행 Close = {close_val:.0f}")
for c in bb.columns:
    v = bb[c].iloc[last_idx]
    rel = "Close보다 위" if v > close_val else ("Close보다 아래" if v < close_val else "Close와 같음")
    print(f"    {c} = {v:.0f}  ({rel})")

# indicators.py 는 bb_cols[0] 을 bb_upper 로, bb_cols[2] 를 bb_lower 로 저장
bb_upper_stored = bb[bb.columns[0]].iloc[last_idx]
bb_lower_stored = bb[bb.columns[2]].iloc[last_idx]
print(f"\n  → indicators.py 저장 시:")
print(f"    bb_upper (실제는 {bb.columns[0]}) = {bb_upper_stored:.0f}")
print(f"    bb_lower (실제는 {bb.columns[2]}) = {bb_lower_stored:.0f}")
if bb_upper_stored < close_val < bb_lower_stored:
    print("  ⚠ upper/lower 라벨이 뒤집힘 (모델 영향은 작지만 의미가 거꾸로)")
elif bb_lower_stored < close_val < bb_upper_stored:
    print("  ✓ upper/lower 라벨 정상")

# ───────── shift(-1) 동작 확인 ─────────
print("\n[shift(-1)] backtest 의 entry_price = Open.shift(-1)")
df['next_close'] = df['Close'].shift(-1)
match = (df['next_close'].iloc[0] == df['Close'].iloc[1])
print(f"  index[0].next_close = {df['next_close'].iloc[0]}")
print(f"  index[1].Close      = {df['Close'].iloc[1]}")
print(f"  → shift(-1) 이 '다음 행' 가져옴 (정상): {match}")
