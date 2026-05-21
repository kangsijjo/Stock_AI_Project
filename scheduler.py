import schedule
import time
import os
import subprocess
import sys
import importlib.util
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()


def _news_module_available():
    """src.processor.news 가 의존하는 transformers 가 설치되어 있는지 점검.
    최소설치(transformers 미설치) 환경에선 뉴스 작업을 건너뛰어 로그 폭발을 막는다.
    """
    return importlib.util.find_spec('transformers') is not None

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
    """매일 06:30 - 데이터 수집 + (가능하면) 뉴스 수집 + KRX 수급 증분"""
    log("===== 일일 데이터 수집 시작 =====")
    run_pipeline('collect')

    # KIS API '투자자별 매매동향' 으로 외국인/기관 일별 순매수 누적.
    # INSERT OR IGNORE 라 매일 호출해도 중복 무해, 어제 1일치만 새로 들어감.
    log("KRX 수급(KIS) 수집 시작...")
    subprocess.run(
        [sys.executable, "-m", "src.collector.supply_demand"],
        check=False
    )

    if _news_module_available():
        log("뉴스/공시 수집 시작...")
        subprocess.run(
            [sys.executable, "-m", "src.processor.news"],
            check=False
        )
    else:
        log("transformers 미설치 - 뉴스/공시 수집 스킵")
    log("===== 일일 데이터 수집 완료 =====")

def morning_scan_job():
    """매일 06:50 - 섹터 스캔"""
    log("===== 모닝 섹터 스캔 시작 =====")
    run_pipeline('scan')
    log("===== 모닝 섹터 스캔 완료 =====")

def korea_trade_job():
    """매일 10:05 - 한국 모의투자 KIS API 매매 + Top-1 paper-trade 기록/청산"""
    log("===== 한국 모의투자 KIS API 매매 시작 =====")
    subprocess.run(
        [sys.executable, "-m", "src.trader.auto_trader"],
        check=False
    )
    log("===== 한국 모의투자 KIS API 매매 완료 =====")

    # Top-1 paper-trade: 실제 매매와 별도. KIS 주문 안 함.
    # record(오늘 신호 기록) + settle(5영업일 지난 pending 청산) 한 번에.
    log("===== 한국 Top-1 paper-trade 기록/청산 =====")
    subprocess.run(
        [sys.executable, "track_top1.py", "all", "--market", "korea"],
        check=False
    )

def korea_intraday_monitor_job():
    """매일 09:00 - 한국장 장중 손절/익절 폴링 모니터 (15:30 자동 종료)
    별도 프로세스로 띄워 매매 작업과 분리한다 (subprocess.Popen 비동기)."""
    log("===== 한국 장중 모니터 시작 =====")
    subprocess.Popen(
        [sys.executable, "-m", "src.trader.intraday_monitor",
         "--market", "korea", "--interval", "60"]
    )

def korea_market_scanner_job():
    """매일 09:00 - 거래량/등락률 상위 종목 분당 폴링 (live_movers 누적, 15:30 자동 종료).
    매수에는 미연결, 데이터 누적만."""
    log("===== 한국 시장 스캐너 시작 =====")
    subprocess.Popen(
        [sys.executable, "-m", "src.trader.market_scanner",
         "--interval", "60", "--count", "20"]
    )

def usa_intraday_monitor_job():
    """매일 23:35 - 미국 장중 손절/익절 폴링 모니터"""
    log("===== 미국 장중 모니터 시작 =====")
    subprocess.Popen(
        [sys.executable, "-m", "src.trader.intraday_monitor",
         "--market", "usa", "--interval", "60"]
    )

def usa_scan_job():
    """매일 22:20 - 미국장 전 스캔"""
    log("===== 미국장 전 섹터 스캔 =====")
    run_pipeline('scan')

def usa_trade_job():
    """매일 22:30 - 미국 모의투자 KIS API 매매 + Top-1 paper-trade"""
    log("===== 미국 모의투자 KIS API 매매 시작 =====")
    subprocess.run(
        [sys.executable, "-m", "src.trader.auto_trader"],
        check=False
    )
    log("===== 미국 모의투자 KIS API 매매 완료 =====")

    log("===== 미국 Top-1 paper-trade 기록/청산 =====")
    subprocess.run(
        [sys.executable, "track_top1.py", "all", "--market", "usa"],
        check=False
    )

def dart_realtime_job():
    """30분마다 DART 공시 수집 + 감성분석.
    transformers 미설치 환경에서는 무동작(스킵). 로그 노이즈 방지."""
    if not _news_module_available():
        return
    log("DART 실시간 공시 수집 시작")
    subprocess.run(
        [sys.executable, "-m", "src.processor.news", "realtime"],
        check=False
    )
    log("DART 실시간 공시 수집 완료")

def weekly_job():
    """매주 일요일 07:00 - 전체 재학습"""
    log("===== 주간 전체 재학습 시작 =====")
    run_pipeline('indicators')
    run_pipeline('train')
    run_pipeline('backtest')
    log("===== 주간 전체 재학습 완료 =====")

# 스케줄 등록
schedule.every().day.at("06:30").do(daily_data_job)               # 데이터 수집
schedule.every().day.at("06:50").do(morning_scan_job)             # 섹터 스캔
schedule.every().day.at("09:00").do(korea_intraday_monitor_job)   # 한국 장중 모니터
schedule.every().day.at("09:00").do(korea_market_scanner_job)     # 한국 시장 스캐너
schedule.every().day.at("10:05").do(korea_trade_job)              # 한국 매매
schedule.every().day.at("22:20").do(usa_scan_job)                 # 미국 스캔
schedule.every().day.at("22:30").do(usa_trade_job)                # 미국 매매
schedule.every().day.at("23:35").do(usa_intraday_monitor_job)     # 미국 장중 모니터
schedule.every(30).minutes.do(dart_realtime_job)                  # DART 30분마다
schedule.every().sunday.at("07:00").do(weekly_job)                # 주간 재학습

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == 'all':
        log("전체 파이프라인 즉시 실행")
        run_pipeline('all')

    elif len(sys.argv) > 1 and sys.argv[1] == 'trade':
        log("매매만 즉시 실행")
        subprocess.run(
            [sys.executable, "-m", "src.trader.auto_trader"],
            check=False
        )

    elif len(sys.argv) > 1 and sys.argv[1] == 'dart':
        log("DART 공시 즉시 수집")
        subprocess.run(
            [sys.executable, "-m", "src.processor.news", "realtime"],
            check=False
        )

    else:
        log("스케줄러 시작")
        log("06:30 데이터 수집 + 뉴스")
        log("06:50 섹터 스캔")
        log("09:00 한국 장중 모니터 시작 (15:30 자동 종료)")
        log("10:05 한국 모의투자")
        log("22:20 미국 스캔")
        log("22:30 미국 모의투자")
        log("23:35 미국 장중 모니터 시작")
        log("30분마다 DART 공시 수집")
        log("일요일 07:00 전체 재학습")
        log("종료: Ctrl+C")

        while True:
            schedule.run_pending()
            time.sleep(60)