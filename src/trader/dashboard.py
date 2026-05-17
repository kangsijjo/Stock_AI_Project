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
        # SQL 인자화 (소소한 안전성 개선)
        df = pd.read_sql(
            "SELECT * FROM finrl_dataset_kr WHERE sector=? ORDER BY date",
            conn, params=[selected_sector]
        )
        conn.close()

        df['date'] = pd.to_datetime(df['date'])

        # 4. backtest.py 와 동일한 비중복·HOLDING_DAYS 모델로 통일
        #    (수수료 양방향 + 세금 + 슬리피지, 진입 후 만기까지 1포지션 유지)
        HOLDING_DAYS = 5
        BUY_FEE, SELL_FEE, TAX, SLIPPAGE = 0.00015, 0.00015, 0.0018, 0.0010
        cost_one_trip = BUY_FEE + SELL_FEE + TAX + 2 * SLIPPAGE

        daily_portfolio = []
        cooldown_until = None
        for date in sorted(df['date'].unique()):
            if cooldown_until is not None and date <= cooldown_until:
                daily_portfolio.append({'date': date, 'daily_return': 0.0})
                continue
            group = df[df['date'] == date]
            top_stock = group.nlargest(1, 'lgbm_prob')
            if not top_stock.empty and float(top_stock.iloc[0]['lgbm_prob']) >= 0.5:
                gross = float(top_stock.iloc[0]['next_return'])
                net = gross - cost_one_trip
                per_day = (1 + net) ** (1 / HOLDING_DAYS) - 1
                for k in range(HOLDING_DAYS):
                    d = pd.Timestamp(date) + pd.tseries.offsets.BDay(k)
                    daily_portfolio.append({'date': d, 'daily_return': per_day})
                cooldown_until = pd.Timestamp(date) + pd.tseries.offsets.BDay(HOLDING_DAYS - 1)
            else:
                daily_portfolio.append({'date': date, 'daily_return': 0.0})

        portfolio = pd.DataFrame(daily_portfolio)
        portfolio = (portfolio.groupby('date', as_index=False)['daily_return']
                              .sum().sort_values('date').reset_index(drop=True))
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