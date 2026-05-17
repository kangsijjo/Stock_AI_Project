@echo off
REM ─────────────────────────────────────────────────────────────
REM 전체 파이프라인을 처음부터 끝까지 한 바퀴 돌리는 스크립트.
REM 첫 셋업 또는 데이터 전체 재구축 시 사용.
REM 소요 시간: 약 6~12시간 (백테스트 9년 walk-forward 포함)
REM
REM 일반 운영은 scheduler.py 가 매일 자동 호출하므로 이 스크립트는 불필요.
REM
REM 각 모듈의 상세 로그는 logs\YYYY-MM-DD.log 에 자동 저장됨.
REM ─────────────────────────────────────────────────────────────

cd /d C:\fin\Stock_AI_Project
call venv\Scripts\activate

echo.
echo ===================================================
echo  Step 0: 데이터 위생 정리 (1회용, 빠름)
echo ===================================================
python fix_date_format.py
python fix_dup_stocks.py
python fix_dup_indicators.py

echo.
echo ===================================================
echo  Step 1: 데이터 수집 (30분 ~ 수 시간)
echo  - 주가 / 거시지표 / 수급
echo ===================================================
python -m src.collector.main_collector
python -m src.collector.macro
python -m src.collector.supply_demand

echo.
echo ===================================================
echo  Step 2: 지표 생성 (30분 ~ 1시간)
echo ===================================================
python -m src.processor.indicators all

echo.
echo ===================================================
echo  Step 3: 모델 학습 (30분 ~ 1시간)
echo ===================================================
python -m src.models.train all

echo.
echo ===================================================
echo  Step 4: 백테스트 (6~9시간, BACKTEST_REBUILD=1)
echo ===================================================
set BACKTEST_REBUILD=1
python -m src.trader.backtest all
set BACKTEST_REBUILD=

echo.
echo ===================================================
echo  Step 5: 검증 진단 (1분)
echo ===================================================
python diag_backtest.py 반도체
python diag_top1.py 반도체

echo.
echo ===================================================
echo  파이프라인 완료
echo  - 상세 로그: logs\YYYY-MM-DD.log
echo  - 다음: run_scheduler.bat 으로 무인 운영 시작
echo ===================================================
pause
