import schedule
import time
import os
from datetime import datetime

def log(msg):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now}] {msg}")

def update_data():
    """매일 주가 데이터 업데이트"""
    log("주가 데이터 업데이트 시작")
    os.system("python -m src.collector.main_collector")
    log("주가 데이터 업데이트 완료")

def update_sectors():
    """섹터 정보 업데이트"""
    log("섹터 정보 업데이트 시작")
    os.system("python -m src.collector.krx_sector")
    log("섹터 정보 업데이트 완료")

def retrain_all():
    """전체 섹터 모델 재학습"""
    log("전체 섹터 모델 재학습 시작")
    os.system("python main.py all")
    log("전체 섹터 모델 재학습 완료")

def daily_job():
    """매일 08:30 - 주가 데이터만 업데이트"""
    log("===== 일일 작업 시작 =====")
    update_data()
    log("===== 일일 작업 완료 =====")

def weekly_job():
    """매주 일요일 09:00 - 섹터 업데이트 + 전체 재학습"""
    log("===== 주간 작업 시작 =====")
    update_data()
    update_sectors()
    retrain_all()
    log("===== 주간 작업 완료 =====")

def run_all():
    """지금 당장 전체 실행"""
    log("===== 전체 작업 시작 =====")
    update_data()
    update_sectors()
    retrain_all()
    log("===== 전체 작업 완료 =====")

# 매일 08:30 주가 업데이트
schedule.every().day.at("08:30").do(daily_job)

# 매주 일요일 09:00 전체 재학습
schedule.every().sunday.at("09:00").do(weekly_job)

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == 'all':
        # 지금 당장 전체 실행
        run_all()
    else:
        # 스케줄러 모드
        log("스케줄러 시작")
        log("매일 08:30 주가 업데이트")
        log("매주 일요일 09:00 전체 재학습")
        log("종료하려면 Ctrl+C")
        
        while True:
            schedule.run_pending()
            time.sleep(60)