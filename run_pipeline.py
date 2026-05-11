import subprocess
import sys
import argparse
from src.logger import get_logger
from src.collector.config import ACTIVE_SECTOR

logger = get_logger('pipeline')

def run_module(module_name, description):
    """지정된 파이썬 모듈을 실행하고 에러 발생 시 파이프라인을 중단합니다."""
    logger.info(f"\n{'='*60}\n▶ [STEP] {description} 시작\n{'='*60}")
    try:
        subprocess.run([sys.executable, "-m", module_name], check=True)
        logger.info(f"▷ [STEP] {description} 완료\n")
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ [STEP] {description} 실패! (에러 코드: {e.returncode})")
        logger.error("데이터 무결성을 위해 파이프라인 가동을 전면 중단합니다.")
        sys.exit(1)

def main():
    # 💡 터미널 명령어를 파싱하는 스위치(인자값) 설정
    parser = argparse.ArgumentParser(description="AI 퀀트 마스터 파이프라인")
    parser.add_argument(
        '--step', 
        type=str, 
        default='all', 
        choices=['all', 'collect', 'indicators', 'train', 'backtest'],
        help="실행할 단계를 선택하세요 (기본값: all)"
    )
    args = parser.parse_args()

    logger.info(f"🚀 [{ACTIVE_SECTOR}] 섹터 마스터 파이프라인 가동 (모드: {args.step})")

    # 각 단계별 모듈 매핑
    steps = {
        'collect': ("src.collector.main_collector", "1. 주가 데이터 수집 (main_collector)"),
        'indicators': ("src.processor.indicators", "2. 지표 전용 DB 생성 (indicators)"),
        'train': ("src.models.train", "3. AI 모델 재학습 (train)"),
        'backtest': ("src.trader.backtest", "4. 백테스트 시뮬레이션 (backtest)")
    }

    # 'all'이면 순서대로 전부 실행, 특정 단계면 해당 모듈만 단독 실행
    if args.step == 'all':
        for key, (module, desc) in steps.items():
            run_module(module, desc)
    else:
        module, desc = steps[args.step]
        run_module(module, desc)

    logger.info(f"🎉 파이프라인 작업({args.step})이 오차 없이 완료되었습니다!")

if __name__ == "__main__":
    main()