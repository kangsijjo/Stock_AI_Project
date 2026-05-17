"""
백테스트 결과 진단:
- 거래당 평균 수익률, 분위수, lgbm_prob 분포 확인
- 비정상으로 큰 누적수익률의 원인이 모델 강도인지 데이터 결함인지 가늠

실행:  python diag_backtest.py [섹터명]
        python diag_backtest.py 반도체
"""
import sys
import sqlite3
import pandas as pd

SECTOR = sys.argv[1] if len(sys.argv) > 1 else '반도체'

conn = sqlite3.connect('data/stock.db')
df = pd.read_sql(
    "SELECT lgbm_prob, next_return FROM finrl_dataset_kr WHERE sector=?",
    conn, params=[SECTOR]
).dropna()

if df.empty:
    print(f"[{SECTOR}] 데이터 없음")
    sys.exit(0)

print(f"=== [{SECTOR}] 백테스트 결과 진단 ===")
print(f"전체 행수: {len(df):,}")

# Top-1 per date 가 아니라 모든 (date, ticker) 행에 대한 분포
print(f"\n[전체 분포]")
print(f"  lgbm_prob 평균: {df['lgbm_prob'].mean():.4f}")
print(f"  lgbm_prob 최대: {df['lgbm_prob'].max():.4f}")
print(f"  next_return 평균: {df['next_return'].mean()*100:+.2f}%")

# 매수 시그널만 (prob >= 0.55)
buy = df[df['lgbm_prob'] >= 0.55]
print(f"\n[매수 시그널 (lgbm_prob>=0.55) — {len(buy):,}건]")
if len(buy) > 0:
    print(f"  next_return 평균: {buy['next_return'].mean()*100:+.2f}%")
    print(f"  next_return std : {buy['next_return'].std()*100:.2f}%")
    print(f"  next_return 분위:")
    for q in [0.1, 0.25, 0.5, 0.75, 0.9]:
        print(f"    {int(q*100)}%: {buy['next_return'].quantile(q)*100:+.2f}%")
    print(f"  승률(>0): {(buy['next_return'] > 0).mean()*100:.1f}%")
    print(f"  +5% 초과 비율: {(buy['next_return'] > 0.05).mean()*100:.1f}%")
    print(f"  +10% 초과 비율: {(buy['next_return'] > 0.10).mean()*100:.1f}%")

# 강한 시그널만 (prob >= 0.8)
strong = df[df['lgbm_prob'] >= 0.8]
print(f"\n[강한 시그널 (lgbm_prob>=0.8) — {len(strong):,}건]")
if len(strong) > 0:
    print(f"  next_return 평균: {strong['next_return'].mean()*100:+.2f}%")
    print(f"  승률(>0): {(strong['next_return'] > 0).mean()*100:.1f}%")

# next_return 극단치 비율 (데이터 결함 가늠)
print(f"\n[next_return 극단치 비율]")
print(f"  |return| > 10%: {(df['next_return'].abs() > 0.10).mean()*100:.2f}%")
print(f"  |return| > 20%: {(df['next_return'].abs() > 0.20).mean()*100:.2f}%")
print(f"  |return| > 30%: {(df['next_return'].abs() > 0.30).mean()*100:.2f}%")

conn.close()
