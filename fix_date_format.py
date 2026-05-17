"""
korea_stocks / usa_stocks 의 date 컬럼이
  - 일부 행: 'YYYY-MM-DD HH:MM:SS'
  - 일부 행: 'YYYY-MM-DD'
두 포맷으로 섞여 있어 indicators 의 pd.to_datetime 이 깨진다.

이 스크립트는 length(date) > 10 행만 골라 앞 10자만 남겨 통일한다.
idempotent — 여러 번 실행해도 안전.

실행:  python fix_date_format.py
"""
import sqlite3
from src.config_db import get_db_path

DB = get_db_path()

with sqlite3.connect(DB) as conn:
    for table in ['korea_stocks', 'usa_stocks']:
        try:
            before = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE length(date) > 10"
            ).fetchone()[0]
            if before == 0:
                print(f"[{table}] 이미 정상 ({before}행 정리 대상 없음)")
                continue

            cur = conn.execute(
                f"UPDATE {table} SET date = substr(date, 1, 10) WHERE length(date) > 10"
            )
            conn.commit()
            print(f"[{table}] {cur.rowcount}행 정리 완료")

        except sqlite3.OperationalError as e:
            print(f"[{table}] 테이블 없음 또는 오류: {e}")

print("DB 정리 완료. 이제 indicators 를 다시 실행하세요.")
