# 전체 파이프라인 PowerShell 버전.
# 사용: .\run_full_pipeline.ps1
# 막힐 때 PowerShell 실행 정책: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

$ErrorActionPreference = "Continue"
Set-Location "C:\fin\Stock_AI_Project"
. .\venv\Scripts\Activate.ps1

function Step($title, $block) {
    Write-Host ""
    Write-Host "=============================================="
    Write-Host " $title"
    Write-Host "=============================================="
    & $block
}

Step "Step 0: 데이터 위생 정리" {
    python fix_date_format.py
    python fix_dup_stocks.py
    python fix_dup_indicators.py
}

Step "Step 1: 데이터 수집 (주가/거시/수급)" {
    python -m src.collector.main_collector
    python -m src.collector.macro
    python -m src.collector.supply_demand
}

Step "Step 2: 지표 생성 (전 섹터)" {
    python -m src.processor.indicators all
}

Step "Step 3: 모델 학습 (전 섹터)" {
    python -m src.models.train all
}

Step "Step 4: 백테스트 (BACKTEST_REBUILD=1, 6~9시간)" {
    $env:BACKTEST_REBUILD = "1"
    python -m src.trader.backtest all
    Remove-Item Env:BACKTEST_REBUILD -ErrorAction SilentlyContinue
}

Step "Step 5: 검증 진단" {
    python diag_backtest.py 반도체
    python diag_top1.py 반도체
}

Write-Host ""
Write-Host "파이프라인 완료. 다음: .\run_scheduler.bat 으로 무인 운영 시작"
Write-Host "상세 로그: logs\YYYY-MM-DD.log"
