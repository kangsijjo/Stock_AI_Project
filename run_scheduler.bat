@echo off
REM ─────────────────────────────────────────────────────────────
REM scheduler.py 자동 재시작 루프.
REM 프로세스가 크래시되면 30초 뒤 다시 시작한다. 부팅 자동 실행
REM (시작프로그램 또는 작업 스케줄러)과 함께 쓰면 무인 운영 가능.
REM 정상 종료(Ctrl+C 2회)는 BREAK 코드 -1073741510 으로 빠져나감.
REM ─────────────────────────────────────────────────────────────
cd /d C:\fin\Stock_AI_Project
call venv\Scripts\activate

set LOGDIR=C:\fin\Stock_AI_Project\logs
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

:loop
echo [%date% %time%] scheduler 시작 >> "%LOGDIR%\runner.log"
python scheduler.py
set EXITCODE=%ERRORLEVEL%
echo [%date% %time%] scheduler 종료 (exit=%EXITCODE%) >> "%LOGDIR%\runner.log"

REM Ctrl+C 로 종료된 경우 재시작하지 않음
if "%EXITCODE%"=="-1073741510" goto end
if "%EXITCODE%"=="3221225786" goto end

REM 그 외 비정상 종료 → 30초 후 재시작
timeout /t 30 /nobreak > nul
goto loop

:end
echo [%date% %time%] runner 종료 (사용자 중단) >> "%LOGDIR%\runner.log"
