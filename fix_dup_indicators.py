"""
korea_indicators / usa_indicators 의 (ticker, date) 중복 행 정리.

원인 추정:
  - indicators 가 여러 번 실행되면서 DELETE 가 sector 단위라
    같은 ticker 가 다른 sector 로 잘못 매핑된 경우 중복 INSERT 발생.

정리 후 UNIQUE 인덱스 추가 → 재발 방지.
실행: python fix_dup_indicators.py
"""
import sqlite3
from src.config_db import get_db_path

DB = get_db_path()

with sqlite3.connect(DB) as conn:
    for table in ['korea_indicators', 'usa_indicators']:
        try:
            before = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            # 중복 제거: 같은 (ticker, date) 중 가장 오래된 rowid 만 남김
            cur = conn.execute(f"""
                DELETE FROM {table}
                WHERE rowid NOT IN (
                    SELECT MIN(rowid) FROM {table} GROUP BY ticker, date
                )
            """)
            conn.commit()
            after = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            removed = before - after
            print(f"[{table}] {before:,} → {after:,} 행 (중복 {removed:,} 제거)")

            # 재발 방지 UNIQUE 인덱스
            try:
                conn.execute(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{table}_tkr_dt "
                    f"ON {table}(ticker, date)"
                )
                print(f"  → UNIQUE 인덱스 추가 (재발 방지)")
            except sqlite3.OperationalError as e:
                print(f"  → UNIQUE 인덱스 추가 실패: {e}")
        except sqlite3.OperationalError as e:
            print(f"[{table}] 테이블 없음 또는 오류: {e}")

print("\n정리 완료.")
