import streamlit as st
import pandas as pd
import plotly.express as px
import sys
import os

# 프로젝트 최상위 경로 인식
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

# 구버전 db.py 대신, 뱅크트리가 개선한 WAL 모드가 적용된 config_db를 사용!
from src.config_db import get_connection

# 페이지 기본 설정
st.set_page_config(page_title="AI 퀀트 백테스트 대시보드", layout="wide")
st.title("📈 AI 모의투자 백테스트 성과 대시보드")

try:
    conn = get_connection()
    # 저장된 백테스트 결과 불러오기
    df = pd.read_sql("SELECT * FROM backtest_results ORDER BY date", conn)
    conn.close()

    if len(df) == 0:
        st.warning("데이터가 없습니다. 백테스트를 먼저 실행해주세요.")
    else:
        # 1. 요약 지표 (KPI) 계산
        final_return = (df['cum_return'].iloc[-1] - 1) * 100
        
        # MDD 계산
        roll_max = df['cum_return'].cummax()
        drawdown = df['cum_return'] / roll_max - 1.0
        max_drawdown = drawdown.min() * 100

        # 샤프비율 계산 (연환산 252일 기준)
        sharpe = (df['daily_return'].mean() / df['daily_return'].std()) * (252 ** 0.5)

        # 화면 상단 지표 카드 (4개로 확장)
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("총 누적 수익률", f"{final_return:,.2f}%")
        col2.metric("최대 낙폭 (MDD)", f"{max_drawdown:,.2f}%")
        col3.metric("샤프비율", f"{sharpe:.2f}")
        col4.metric("백테스트 기간", f"{df['date'].iloc[0][:10]} ~ {df['date'].iloc[-1][:10]}")

        # 2. 누적 수익률 차트 (Plotly 사용)
        st.subheader("📊 누적 자산 변화 추이")
        fig = px.line(df, x='date', y='cum_return', title='AI 포트폴리오 누적 자산 (1.0 = 원금)')
        fig.update_layout(yaxis_title="누적 자본", xaxis_title="날짜")
        fig.update_traces(fill='tozeroy', line_color='#00b4d8') 
        st.plotly_chart(fig, use_container_width=True)

        # 3. 하단 상세 데이터 표
        st.subheader("📝 일별 상세 데이터 (최근 10일)")
        st.dataframe(df.tail(10), use_container_width=True)

except Exception as e:
    st.error(f"DB를 읽어오는 중 에러가 발생했습니다: {e}")