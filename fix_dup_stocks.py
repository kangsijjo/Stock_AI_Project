"""
korea_stocks / usa_stocks 의 (ticker, date) 중복 행 정리 + UNIQUE 인덱스.
indicators 와 같은 방식.

실행: python fix_dup_stocks.py
"""
import sqlite3
from src.config_db import get_db_path

DB = get_db_path()

with sqlite3.connect(DB) as conn:
    for table in ['korea_stocks', 'usa_stocks']:
        try:
            before = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            conn.execute(f"""
                DELETE FROM {table}
                WHERE rowid NOT IN (
                    SELECT MIN(rowid) FROM {table} GROUP BY ticker, date
                )
            """)
            conn.commit()
            after = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            removed = before - after
            print(f"[{table}] {before:,} → {after:,} 행 (중복 {removed:,} 제거)")

            try:
                conn.execute(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{table}_tkr_dt "
                    f"ON {table}(ticker, date)"
                )
                print(f"  → UNIQUE 인덱스 추가 (재발 방지)")
            except sqlite3.OperationalError as e:
                print(f"  → UNIQUE 인덱스 추가 실패: {e}")
        except sqlite3.OperationalError as e:
            print(f"[{table}] 오류: {e}")

print("\n정리 완료.")
