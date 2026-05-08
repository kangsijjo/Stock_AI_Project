import schedule
import time
import subprocess
import os
from datetime import datetime

def log(msg):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now}] {msg}")

def update_data():
    """매일 데이터 업데이트"""
    log("데이터 업데이트 시작")
    os.system("python -m src.collector.main_collector")
    log("데이터 업데이트 완료")

def update_sectors():
    """섹터 정보 업데이트"""
    log("섹터 정보 업데이트 시작")
    os.system("python -m src.collector.krx_sector")
    log("섹터 정보 업데이트 완료")

def retrain_model():
    """모델 재학습"""
    log("모델 재학습 시작")
    os.system("python -m src.models.train")
    log("모델 재학습 완료")

def daily_job():
    """매일 실행할 작업"""
    log("===== 일일 자동화 시작 =====")
    update_data()
    update_sectors()
    retrain_model()
    log("===== 일일 자동화 완료 =====")

# 매일 오전 8시 30분 실행 (장 시작 전)
schedule.every().day.at("08:30").do(daily_job)

log("스케줄러 시작 - 매일 08:30 자동 실행")
log("종료하려면 Ctrl+C")

while True:
    schedule.run_pending()
    time.sleep(60)