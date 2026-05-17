"""
[DEPRECATED]
이 파일은 src/collector/db.py 의 save_stock / load_sector 와 거의 동일한
중복 코드였습니다. 신규 코드는 src/collector/db.py 를 사용합니다.

다음 명령으로 git 추적에서 안전하게 제거하세요:
    git rm make_index.py
    git commit -m "remove dead code: make_index.py duplicated db.py"
"""
import warnings
warnings.warn(
    "make_index.py is deprecated. Use src.collector.db instead.",
    DeprecationWarning,
    stacklevel=2,
)
