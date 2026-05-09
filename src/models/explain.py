import shap
import pickle
import pandas as pd
import numpy as np
import sqlite3
import os
import matplotlib
matplotlib.rcParams['font.family'] = 'Malgun Gothic'
matplotlib.rcParams['axes.unicode_minus'] = False
import matplotlib.pyplot as plt

from src.config_db import get_db_path
DB_PATH = get_db_path()

from src.config_db import get_connection

def get_latest_features(ticker, market='korea'):
    """최신 피처 생성"""
    conn = get_connection()
    table = 'korea_stocks' if market == 'korea' else 'usa_stocks'
    df = pd.read_sql(
        f"SELECT * FROM {table} WHERE ticker=? ORDER BY date DESC LIMIT 100",
        conn, params=[ticker]
    )
    conn.close()

    if len(df) < 61:
        return None

    df = df.sort_values('date').reset_index(drop=True)
    c = df['Close'].values
    v = df['Volume'].values

    return_1d  = (c[-1] - c[-2]) / c[-2]
    return_5d  = (c[-1] - c[-6]) / c[-6]
    return_20d = (c[-1] - c[-21]) / c[-21]

    ma5_ratio  = c[-1] / c[-5:].mean()
    ma20_ratio = c[-1] / c[-20:].mean()
    ma60_ratio = c[-1] / c[-60:].mean()

    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0).rolling(14).mean().iloc[-1]
    loss = (-delta.clip(upper=0)).rolling(14).mean().iloc[-1]
    rsi = 100 - (100 / (1 + gain / loss)) if loss != 0 else 50

    vol_ratio  = v[-1] / v[-20:].mean() if v[-20:].mean() > 0 else 1
    volatility = pd.Series(c).pct_change().rolling(20).std().iloc[-1]

    return pd.DataFrame([[
        return_1d, return_5d, return_20d,
        ma5_ratio, ma20_ratio, ma60_ratio,
        rsi, vol_ratio, volatility
    ]], columns=[
        'return_1d', 'return_5d', 'return_20d',
        'ma5_ratio', 'ma20_ratio', 'ma60_ratio',
        'rsi', 'vol_ratio', 'volatility'
    ])

def explain_prediction(ticker, sector, market='korea'):
    """특정 종목 예측 근거 설명"""
    print(f"\n=== {ticker} 예측 근거 분석 ===")

    # 모델 로드
    model_path = f'src/models/saved/{sector}_model.pkl'
    with open(model_path, 'rb') as f:
        model = pickle.load(f)

    # 피처 생성
    features = get_latest_features(ticker, market)
    if features is None:
        print("데이터 부족")
        return

    # 예측 확률
    prob = model.predict_proba(features)[0][1]
    print(f"상승확률: {prob:.2%}")
    print(f"판단: {'매수' if prob >= 0.6 else '매도' if prob <= 0.4 else '관망'}")

    # 피처 값 출력
    print(f"\n=== 현재 지표 상태 ===")
    feature_names_kr = {
        'return_1d':   '1일 수익률',
        'return_5d':   '5일 수익률',
        'return_20d':  '20일 수익률',
        'ma5_ratio':   '5일 이평 대비',
        'ma20_ratio':  '20일 이평 대비',
        'ma60_ratio':  '60일 이평 대비',
        'rsi':         'RSI',
        'vol_ratio':   '거래량 비율',
        'volatility':  '변동성',
    }
    for col in features.columns:
        val = features[col].values[0]
        kr_name = feature_names_kr.get(col, col)
        if 'ratio' in col:
            print(f"  {kr_name}: {val:.3f} ({'위' if val > 1 else '아래'})")
        elif col == 'rsi':
            status = '과매수' if val > 70 else '과매도' if val < 30 else '중립'
            print(f"  {kr_name}: {val:.1f} ({status})")
        elif 'return' in col:
            print(f"  {kr_name}: {val*100:.2f}%")
        else:
            print(f"  {kr_name}: {val:.4f}")

    # SHAP 분석
    print(f"\n=== AI 판단 근거 (SHAP) ===")
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(features)

    # 분류 모델은 shap_values가 리스트
    if isinstance(shap_values, list):
        sv = shap_values[1][0]  # 상승(1) 클래스
    else:
        sv = shap_values[0]

    # 피처별 기여도 출력
    contributions = list(zip(features.columns, sv))
    contributions.sort(key=lambda x: abs(x[1]), reverse=True)

    for feat, contrib in contributions:
        kr_name = feature_names_kr.get(feat, feat)
        direction = '📈 상승 기여' if contrib > 0 else '📉 하락 기여'
        print(f"  {kr_name}: {contrib:+.4f} ({direction})")

    # 시각화
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    fig.suptitle(f'{ticker} ({sector}) 예측 근거 분석 - 상승확률: {prob:.2%}', fontsize=13)

    # 1. SHAP 막대차트
    ax1 = axes[0]
    feats = [feature_names_kr.get(f, f) for f, _ in contributions]
    values = [v for _, v in contributions]
    colors = ['red' if v > 0 else 'blue' for v in values]
    ax1.barh(feats, values, color=colors)
    ax1.axvline(x=0, color='black', linewidth=0.5)
    ax1.set_title('AI 판단 근거 (양수=상승기여, 음수=하락기여)')
    ax1.set_xlabel('SHAP 값')

    # 2. 현재 지표 상태
    ax2 = axes[1]
    indicator_vals = []
    indicator_names = []
    for col in ['rsi', 'ma5_ratio', 'ma20_ratio', 'vol_ratio',
                'return_1d', 'return_5d']:
        if col in features.columns:
            val = features[col].values[0]
            indicator_names.append(feature_names_kr.get(col, col))
            if col == 'rsi':
                indicator_vals.append((val - 50) / 50)
            elif 'ratio' in col:
                indicator_vals.append(val - 1)
            else:
                indicator_vals.append(val)

    colors2 = ['red' if v > 0 else 'blue' for v in indicator_vals]
    ax2.barh(indicator_names, indicator_vals, color=colors2)
    ax2.axvline(x=0, color='black', linewidth=0.5)
    ax2.set_title('현재 지표 상태')

    plt.tight_layout()
    os.makedirs('backtest/charts', exist_ok=True)
    chart_path = f'backtest/charts/{ticker}_explain.png'
    plt.savefig(chart_path, dpi=100, bbox_inches='tight')
    print(f"\n차트 저장: {chart_path}")
    plt.show()

if __name__ == "__main__":
    from src.collector.config import ACTIVE_SECTOR
    usa_sectors = ['Industrials', 'Financials', 'Information Technology',
                   'Health Care', 'Consumer Discretionary', 'Consumer Staples',
                   'Utilities', 'Real Estate', 'Materials',
                   'Communication Services', 'Energy']
    market = 'usa' if ACTIVE_SECTOR in usa_sectors else 'korea'

    # 반도체 대표 종목으로 테스트
    ticker = '005930' if market == 'korea' else 'XOM'
    explain_prediction(ticker, ACTIVE_SECTOR, market)