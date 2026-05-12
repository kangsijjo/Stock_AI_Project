import streamlit as st
import pandas as pd
import plotly.express as px
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))
from src.config_db import get_connection

st.set_page_config(page_title="AI 퀀트 백테스트 대시보드", layout="wide")
st.title("📈 AI 전 섹터 워크포워드 성과 대시보드")

try:
    conn = get_connection()
    # 1. DB에 저장된 섹터 목록 불러오기
    sectors_df = pd.read_sql("SELECT DISTINCT sector FROM finrl_dataset_kr", conn)
    
    if len(sectors_df) == 0:
        st.warning("데이터가 없습니다. 파이프라인 백테스트를 먼저 실행해주세요.")
        conn.close()
    else:
        sector_list = sectors_df['sector'].tolist()
        
        # 2. 섹터 선택 드롭다운 생성
        selected_sector = st.selectbox("📊 분석할 섹터를 선택하세요", sector_list)

        # 3. 선택한 섹터의 FinRL 교과서 데이터만 로드
        df = pd.read_sql(f"SELECT * FROM finrl_dataset_kr WHERE sector='{selected_sector}' ORDER BY date", conn)
        conn.close()

        df['date'] = pd.to_datetime(df['date'])
        
        # 4. 수수료 방어(Hold) 로직을 대시보드에서 실시간 재현
        daily_portfolio = []
        current_holding_ticker = None

        for date, group in df.groupby('date'):
            top_stock = group.nlargest(1, 'lgbm_prob')
            
            if not top_stock.empty and float(top_stock.iloc[0]['lgbm_prob']) >= 0.5:
                best_ticker = top_stock.iloc[0]['tic']
                day_return = float(top_stock.iloc[0]['next_return'])
                
                # 종목 변경 시에만 수수료 0.35% 차감
                if current_holding_ticker != best_ticker:
                    day_return -= 0.0035
                    current_holding_ticker = best_ticker
            else:
                day_return = 0.0 
                if current_holding_ticker is not None:
                    current_holding_ticker = None
                    
            daily_portfolio.append({'date': date, 'daily_return': day_return})

        portfolio = pd.DataFrame(daily_portfolio).sort_values('date')
        portfolio['cum_return'] = (1 + portfolio['daily_return']).cumprod()

        # 5. 요약 지표 (KPI) 계산
        final_return = (portfolio['cum_return'].iloc[-1] - 1) * 100
        mdd = (portfolio['cum_return'] / portfolio['cum_return'].cummax() - 1).min() * 100
        std = portfolio['daily_return'].std()
        sharpe = (portfolio['daily_return'].mean() / std * (252 ** 0.5)) if std > 0 else 0

        # 화면 상단 지표 카드
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("총 누적 수익률", f"{final_return:,.2f}%")
        col2.metric("최대 낙폭 (MDD)", f"{mdd:,.2f}%")
        col3.metric("샤프비율", f"{sharpe:.2f}")
        col4.metric("백테스트 기간", f"{portfolio['date'].iloc[0].strftime('%Y-%m-%d')} ~ {portfolio['date'].iloc[-1].strftime('%Y-%m-%d')}")

        # 6. 누적 수익률 차트
        st.subheader(f"📊 [{selected_sector}] 누적 자산 변화 추이")
        fig = px.line(portfolio, x='date', y='cum_return', title='AI 포트폴리오 누적 자산 (1.0 = 원금)')
        fig.update_layout(yaxis_title="누적 자본", xaxis_title="날짜")
        fig.update_traces(fill='tozeroy', line_color='#00b4d8') 
        st.plotly_chart(fig, use_container_width=True)

except Exception as e:
    st.error(f"에러가 발생했습니다: {e}")