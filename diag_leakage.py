"""
모델 누수(leakage) 원인 추적용 진단 스크립트.

1. korea_indicators 테이블 컬럼 전체 — 의심 컬럼 식별
2. 저장된 모델의 feature_importance Top 15 — 모델이 가장 의존하는 피처
3. macro_indicators 날짜 범위 — 시점 정렬 점검

실행: python diag_leakage.py [섹터명]
       python diag_leakage.py 반도체
"""
import sys
import os
import sqlite3
import pickle
import pandas as pd

SECTOR = sys.argv[1] if len(sys.argv) > 1 else '반도체'
conn = sqlite3.connect('data/stock.db')

# ────────────────────────────────────────────────
# 1. korea_indicators 컬럼 전체
# ────────────────────────────────────────────────
print(f"\n=== 1. korea_indicators 테이블 컬럼 ===")
try:
    cols = [c[1] for c in conn.execute('PRAGMA table_info(korea_indicators)').fetchall()]
    for c in cols:
        print(f"  - {c}")
    print(f"총 {len(cols)} 컬럼")
except Exception as e:
    print(f"실패: {e}")

# ────────────────────────────────────────────────
# 2. 저장된 모델 feature_importance Top 15
# ────────────────────────────────────────────────
print(f"\n=== 2. [{SECTOR}] 모델 feature_importance Top 15 ===")
model_path = f'src/models/saved/{SECTOR}_model.pkl'
if not os.path.exists(model_path):
    print(f"모델 파일 없음: {model_path}  →  train 부터 다시 실행 필요")
else:
    try:
        with open(model_path, 'rb') as f:
            obj = pickle.load(f)
        if isinstance(obj, dict) and 'model' in obj:
            model = obj['model']
            features = obj.get('features')
        else:
            model = obj
            features = None

        if features is None:
            features = getattr(model, 'feature_name_', None) \
                       or getattr(model, 'feature_names_in_', None)

        if hasattr(model, 'feature_importances_') and features is not None:
            imp = pd.DataFrame({
                'feature': list(features),
                'importance': model.feature_importances_
            }).sort_values('importance', ascending=False)
            for _, r in imp.head(15).iterrows():
                bar = '█' * int(r['importance'] / max(imp['importance'].max(), 1) * 30)
                print(f"  {r['feature']:20s} {r['importance']:8.0f}  {bar}")
        else:
            print("feature_importance 추출 실패")
    except Exception as e:
        print(f"모델 분석 실패: {e}")

# ────────────────────────────────────────────────
# 3. macro_indicators 날짜 범위 (시점 정렬 점검)
# ────────────────────────────────────────────────
print(f"\n=== 3. macro_indicators 날짜 범위 ===")
try:
    macro = pd.read_sql(
        "SELECT indicator, MIN(date) AS min_date, MAX(date) AS max_date, COUNT(*) AS rows "
        "FROM macro_indicators GROUP BY indicator",
        conn
    )
    print(macro.to_string(index=False))
    print("\n→ korea_indicators 의 한국 거래일 max date 와 비교해 미국 macro 가 +1일 앞서 있는지 확인")
    kr_max = conn.execute("SELECT MAX(date) FROM korea_indicators").fetchone()[0]
    print(f"  korea_indicators max date: {kr_max}")
except Exception as e:
    print(f"macro 분석 실패: {e}")

conn.close()
