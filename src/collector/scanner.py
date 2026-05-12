import pandas as pd
import numpy as np
from src.config_db import get_connection
from src.logger import get_logger
# 보스의 config.py 구조를 100% 활용합니다.
from src.collector.config import ACTIVE_SECTOR, update_active_sector

logger = get_logger('scanner')

def scan_best_sector(market='korea'):
    logger.info(f"=== 🚀 주도 섹터 정찰 시작 (현재 타겟: {ACTIVE_SECTOR}) ===")
    conn = get_connection()
    table = 'korea_stocks' if market == 'korea' else 'usa_stocks'
    
    try:
        # [방어] sector가 NULL이거나 데이터가 오염된 종목 필터링
        query = f"""
            SELECT date, ticker, sector, Close 
            FROM {table} 
            WHERE date >= date((SELECT MAX(date) FROM {table}), '-30 days')
            AND sector IS NOT NULL 
            AND sector != '' 
            AND sector != 'None'
        """
        df = pd.read_sql(query, conn)
    except Exception as e:
        logger.error(f"스캐너 데이터 로드 실패: {e}")
        conn.close()
        return None
    conn.close()

    if df.empty:
        logger.error("스캔할 데이터가 없습니다.")
        return None

    momentum_list = []
    
    # [최적화] 단순 수익률이 아닌 변동성 대비 수익률(위험 조정 점수) 산출
    for sector, group in df.groupby('sector'):
        sector_scores = []
        for ticker, t_group in group.groupby('ticker'):
            t_group = t_group.sort_values('date')
            if len(t_group) >= 5: # 최소 5일치 데이터는 있어야 변동성 계산 가능
                t_group['daily_ret'] = t_group['Close'].pct_change()
                
                total_ret = (t_group.iloc[-1]['Close'] - t_group.iloc[0]['Close']) / t_group.iloc[0]['Close']
                volatility = t_group['daily_ret'].std() * np.sqrt(252) # 연환산 변동성
                
                if volatility > 0 and not np.isnan(volatility):
                    # 샤프 지수 개념의 위험 조정 점수 (단순 급등주 걸러내기)
                    score = total_ret / volatility
                    sector_scores.append(score)
        
        if sector_scores:
            avg_score = sum(sector_scores) / len(sector_scores)
            momentum_list.append({'sector': sector, 'score': avg_score})
    
    if not momentum_list:
        return None

    momentum_df = pd.DataFrame(momentum_list).sort_values('score', ascending=False)
    
    best_sector = momentum_df.iloc[0]['sector']
    best_score = momentum_df.iloc[0]['score']
    
    # 현재 적용 중인 섹터의 점수 확인
    current_sector_row = momentum_df[momentum_df['sector'] == ACTIVE_SECTOR]
    current_score = current_sector_row.iloc[0]['score'] if not current_sector_row.empty else -999

    logger.info("📊 [섹터별 위험 조정 점수 TOP 3]")
    for i, (idx, row) in enumerate(momentum_df.head(3).iterrows()):
        marker = " (현재)" if row['sector'] == ACTIVE_SECTOR else ""
        logger.info(f"  {i+1}위: {row['sector']} (Score: {row['score']:.4f}){marker}")

    # [교체 전략] 새로운 1위가 기존보다 15% 이상 압도적일 때만 갈아타기 (수수료 방어)
    SWITCH_THRESHOLD = 1.15 
    
    if best_sector == ACTIVE_SECTOR:
        logger.info(f"✅ [{ACTIVE_SECTOR}]가 여전히 시장 주도주입니다. 유지를 결정합니다.")
        return ACTIVE_SECTOR
    elif best_score > (current_score * SWITCH_THRESHOLD) or current_score < 0:
        logger.info(f"🔄 주도 섹터 교체 감지: [{ACTIVE_SECTOR}] -> [{best_sector}]")
        return best_sector
    else:
        logger.info(f"🛡️ 1위가 [{best_sector}]로 바뀌었으나 차이가 크지 않아 기존 [{ACTIVE_SECTOR}]를 유지합니다.")
        return ACTIVE_SECTOR

if __name__ == "__main__":
    target_sector = scan_best_sector()
    if target_sector and target_sector != ACTIVE_SECTOR:
        # 보스의 config.py에 정의된 YAML 업데이트 함수 호출
        update_active_sector(target_sector)
        logger.info(f"⚙️ config.yaml 업데이트 완료 -> {target_sector}")
    else:
        logger.info("⚙️ 현재 섹터 유지")