"""
indicators.py 의 macro_pivot.shift(1) 이 실제로 적용됐는지 검증.

비교: 한국 종목 t일 features 의 nasdaq_chg 값  vs  macro_indicators 의 NASDAQ t/t-1 값
- 한국 t일과 macro t일이 같으면 shift 안 됐음 (leakage)
- 한국 t일과 macro t-1일이 같으면 shift 정상 적용됨
"""
import sqlite3
import pandas as pd

conn = sqlite3.connect('data/stock.db')

# 1. 한국 indicators 의 한 종목 최근 행 (samsung)
sample = pd.read_sql("""
    SELECT date, nasdaq_chg, sox_chg, vix_chg
    FROM korea_indicators
    WHERE ticker='005930' AND date >= '2025-01-01'
    ORDER BY date DESC LIMIT 7
""", conn)
print("[korea_indicators 005930 최근 7일 (가장 최근이 위)]")
print(sample.to_string(index=False))

# 2. 같은 기간 macro_indicators NASDAQ
macro = pd.read_sql("""
    SELECT date, indicator, change_pct
    FROM macro_indicators
    WHERE indicator IN ('NASDAQ', 'SOX', 'VIX')
      AND date >= '2025-01-01'
    ORDER BY indicator, date DESC LIMIT 21
""", conn)
print("\n[macro_indicators 같은 기간]")
print(macro.to_string(index=False))

print("\n[해석]")
print("한국 t일 nasdaq_chg 값이 macro t일 NASDAQ change_pct 와 같으면 → shift 안 됨 = leakage")
print("한국 t일 nasdaq_chg 값이 macro t-1일 NASDAQ change_pct 와 같으면 → shift 적용 = OK")

conn.close()
