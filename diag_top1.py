"""
매수 시그널 전체 평균 vs 매일 Top-1 의 평균 비교.
누적 계산이 사용하는 건 매일 Top-1 만이라, 이게 진짜 baseline.
"""
import sys
import sqlite3
import pandas as pd

SECTOR = sys.argv[1] if len(sys.argv) > 1 else '반도체'
conn = sqlite3.connect('data/stock.db')
df = pd.read_sql(
    "SELECT date, tic, lgbm_prob, next_return FROM finrl_dataset_kr WHERE sector=?",
    conn, params=[SECTOR]
).dropna()
conn.close()

print(f"\n[{SECTOR}] Top-1 분석")
print(f"전체 행수: {len(df):,}")

# 매일 Top-1 종목 (lgbm_prob 가장 높은 1개)
idx = df.groupby('date')['lgbm_prob'].idxmax()
top1 = df.loc[idx]
print(f"고유 거래일: {len(top1):,}")

# Top-1 중 prob>=0.55 인 날만 실제 거래
top1_buy = top1[top1['lgbm_prob'] >= 0.55]
print(f"\n[매수 발생일 (Top-1 prob>=0.55)]: {len(top1_buy):,}일")
if len(top1_buy):
    print(f"  next_return 평균: {top1_buy['next_return'].mean()*100:+.2f}%")
    print(f"  next_return std : {top1_buy['next_return'].std()*100:.2f}%")
    print(f"  승률(>0): {(top1_buy['next_return']>0).mean()*100:.1f}%")
    print(f"  분위 10/25/50/75/90:")
    for q in [0.1, 0.25, 0.5, 0.75, 0.9]:
        print(f"    {int(q*100):>2}%: {top1_buy['next_return'].quantile(q)*100:+.2f}%")

# 전체 매수 시그널과 비교
all_buy = df[df['lgbm_prob'] >= 0.55]
print(f"\n[참고 - 전체 매수 시그널]: {len(all_buy):,}건")
if len(all_buy):
    print(f"  next_return 평균: {all_buy['next_return'].mean()*100:+.2f}%")
