import schedule
import time
import subprocess
import sys
from src.logger import get_logger

logger = get_logger('scheduler')

def run_master_pipeline():
    """매일 자정(00:00)에 마스터 파이프라인 전체 단계 실행"""
    logger.info("===== 🌙 자정 마스터 파이프라인 가동 시작 =====")
    try:
        subprocess.run([sys.executable, "run_pipeline.py", "--step", "all"], check=True)
        logger.info("===== 🌙 자정 마스터 파이프라인 가동 완료 =====")
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ 파이프라인 실행 실패! 에러코드: {e.returncode}")

def run_auto_trader():
    """매일 아침(10:00)에 한국 주식 모의투자 자동매매 실행"""
    logger.info("===== ☀️ 오전장 안정기(10:00) 자동매매 가동 시작 =====")
    try:
        # auto_trader.py를 모듈로 실행하여 자동매매 트리거
        subprocess.run([sys.executable, "-m", "src.trader.auto_trader"], check=True)
        logger.info("===== ☀️ 오전장 자동매매 가동 완료 =====")
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ 자동매매 실행 실패! 에러코드: {e.returncode}")

# 1. 매일 00시 00분에 데이터 수집 및 학습 실행
schedule.every().day.at("00:00").do(run_master_pipeline)

# 2. 매일 10시 00분에 한국장 모의투자 매매 실행 (변동성 안정기)
schedule.every().day.at("10:00").do(run_auto_trader)

if __name__ == "__main__":
    logger.info("🕒 퀀트 자동화 스케줄러 가동을 시작합니다. (종료: Ctrl+C)")
    logger.info(" - 등록된 작업 1: 매일 00:00 마스터 파이프라인 (스캔~백테스트)")
    logger.info(" - 등록된 작업 2: 매일 10:00 실전/모의 자동매매 (한국장 안정기)")
    
    while True:
        schedule.run_pending()
        time.sleep(60)