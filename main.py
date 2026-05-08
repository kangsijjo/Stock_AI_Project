import os
import sqlite3
import pandas as pd

DB_PATH = 'data/stock.db'

def get_available_sectors():
    """DB에서 사용 가능한 섹터 목록 가져오기"""
    conn = sqlite3.connect(DB_PATH)
    
    korea_sectors = pd.read_sql(
        "SELECT DISTINCT sector, COUNT(DISTINCT ticker) as 종목수 FROM korea_stocks WHERE sector IS NOT NULL GROUP BY sector ORDER BY 종목수 DESC",
        conn
    )
    
    usa_sectors = pd.read_sql(
        "SELECT DISTINCT sector, COUNT(DISTINCT ticker) as 종목수 FROM usa_stocks WHERE sector IS NOT NULL GROUP BY sector ORDER BY 종목수 DESC",
        conn
    )
    conn.close()
    return korea_sectors, usa_sectors

def update_config(sector):
    """config.py ACTIVE_SECTOR 자동 변경"""
    config_path = 'src/collector/config.py'
    with open(config_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if line.startswith('ACTIVE_SECTOR'):
            lines[i] = f'ACTIVE_SECTOR = "{sector}"'
            break
    
    with open(config_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    
    print(f"섹터 변경 완료: {sector}")

def run_pipeline(sector, market):
    """기술지표 → 모델학습 → 백테스트 자동 실행"""
    import subprocess
    
    print(f"\n{'='*50}")
    print(f"섹터: {sector} / 시장: {market}")
    print(f"{'='*50}")
    
    # 1. config 업데이트
    update_config(sector)
    
    # 2. 기술지표 생성
    print("\n[1/3] 기술지표 생성 중...")
    os.system("python -m src.processor.indicators")
    
    # 3. 모델 학습
    print("\n[2/3] 모델 학습 중...")
    os.system("python -m src.models.train")
    
    # 4. 백테스트
    print("\n[3/3] 백테스트 실행 중...")
    os.system("python -m backtest.backtest")

def main():
    print("\n" + "="*50)
    print("      Stock AI - 섹터 분석 시스템")
    print("="*50)
    
    korea_sectors, usa_sectors = get_available_sectors()
    
    # 섹터 목록 출력
    all_sectors = []
    
    print("\n[한국 섹터]")
    for _, row in korea_sectors.iterrows():
        all_sectors.append((row['sector'], 'korea'))
        print(f"  {len(all_sectors)}. {row['sector']} ({row['종목수']}개 종목)")
    
    print("\n[미국 섹터]")
    for _, row in usa_sectors.iterrows():
        all_sectors.append((row['sector'], 'usa'))
        print(f"  {len(all_sectors)}. {row['sector']} ({row['종목수']}개 종목)")
    
    print("\n  0. 종료")
    
    # 섹터 선택
    while True:
        try:
            choice = int(input("\n섹터 번호 선택: "))
            if choice == 0:
                print("종료합니다.")
                break
            elif 1 <= choice <= len(all_sectors):
                sector, market = all_sectors[choice - 1]
                run_pipeline(sector, market)
                break
            else:
                print("올바른 번호를 입력해주세요.")
        except ValueError:
            print("숫자를 입력해주세요.")

if __name__ == "__main__":
    main()