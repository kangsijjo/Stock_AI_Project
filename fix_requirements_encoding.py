"""
requirements.txt 가 UTF-16 LE로 저장돼 있어 pip install -r 가 실패합니다.
이 스크립트를 1회 실행하면 UTF-8(BOM 없음)로 재저장합니다.

실행:  python fix_requirements_encoding.py
"""
import os, codecs

SRC = os.path.join(os.path.dirname(__file__), 'requirements.txt')
BAK = SRC + '.utf16.bak'

with open(SRC, 'rb') as f:
    raw = f.read()

# UTF-16 BOM 자동 감지
if raw.startswith(codecs.BOM_UTF16_LE) or raw.startswith(codecs.BOM_UTF16_BE):
    text = raw.decode('utf-16')
elif b'\x00' in raw[:200]:           # BOM 없는 UTF-16 추정
    text = raw.decode('utf-16-le', errors='ignore')
else:
    print('이미 UTF-8 입니다. 변환 불필요.')
    raise SystemExit(0)

os.rename(SRC, BAK)
with open(SRC, 'w', encoding='utf-8', newline='\n') as f:
    f.write(text.replace('\r\n', '\n'))
print(f'변환 완료. 백업: {BAK}')
