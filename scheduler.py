import schedule
import time
import os
import subprocess
import sys
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

def log(msg):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now}] {msg}")

def run_pipeline(step):
    """run_pipeline.py 실행"""
    log(f"파이프라인 실행: --step {step}")
    subprocess.run(
        [sys.executable, "run_pipeline.py", "--step", step],
        check=False
    )

def daily_data_job():
    """매일 06:30 - 데이터 수집"""
    log("===== 일일 데이터 수집 시작 =====")
    run_pipeline('collect')
    log("===== 일일 데이터 수집 완료 =====")

def morning_scan_job():
    """매일 06:50 - 섹터 스캔"""
    log("===== 모닝 섹터 스캔 시작 =====")
    run_pipeline('scan')
    log("===== 모닝 섹터 스캔 완료 =====")

def korea_trade_job():
    log("===== 한국 모의투자 KIS API 매매 시작 =====")
    subprocess.run(
        [sys.executable, "-m", "src.trader.auto_trader"],
        check=False
    )
    log("===== 한국 모의투자 KIS API 매매 완료 =====")

def usa_scan_job():
    """매일 22:20 - 미국장 전 스캔"""
    log("===== 미국장 전 섹터 스캔 =====")
    run_pipeline('scan')

def usa_trade_job():
    """매일 22:30 - 미국 모의투자 매매"""
    log("===== 미국 모의투자 매매 시작 =====")
    # 미국 섹터로 전환 후 매매
    subprocess.run(
        [sys.executable, "-m", "src.trader.rule_trader", "all"],
        check=False
    )
    log("===== 미국 모의투자 매매 완료 =====")

def weekly_job():
    """매주 일요일 07:00 - 전체 재학습"""
    log("===== 주간 전체 재학습 시작 =====")
    run_pipeline('indicators')
    run_pipeline('train')
    run_pipeline('backtest')
    log("===== 주간 전체 재학습 완료 =====")

# 스케줄 등록
schedule.every().day.at("06:30").do(daily_data_job)
schedule.every().day.at("06:50").do(morning_scan_job)
schedule.every().day.at("10:00").do(korea_trade_job)
schedule.every().day.at("22:20").do(usa_scan_job)
schedule.every().day.at("22:30").do(usa_trade_job)
schedule.every().sunday.at("07:00").do(weekly_job)

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == 'all':
        log("전체 파이프라인 즉시 실행")
        run_pipeline('all')

    elif len(sys.argv) > 1 and sys.argv[1] == 'trade':
        log("매매만 즉시 실행")
        run_pipeline('trade')

    else:
        log("스케줄러 시작")
        log("06:30 데이터 수집")
        log("06:50 섹터 스캔")
        log("10:00 한국 모의투자")
        log("22:20 미국 스캔")
        log("22:30 미국 모의투자")
        log("일요일 07:00 전체 재학습")
        log("종료: Ctrl+C")

        while True:
            schedule.run_pending()
            time.sleep(60)