"""
실거래(모의투자 포함) 결과 vs 백테스트 예측 비교 리포트.

목적
----
- 백테스트의 슬리피지/수수료 가정이 현실과 얼마나 다른지 실측
- 모델 시그널의 실제 적중률(개별 거래 단위) 확인
- "회귀 모델로 갈아탈 가치가 있는지" 결정용 근거 데이터 마련

매칭 규칙
--------
실제 거래(positions 테이블의 closed 행) 의 (ticker, buy_date)
↔ finrl_dataset_kr/us 의 (tic, date) 매칭.
- buy_date 가 백테스트 데이터에 정확히 없으면, 이전 영업일로 fallback 매칭.

출력
----
- 콘솔: 거래 수, 평균 실현/예상 수익, 갭(=실현-예상)의 평균/표준편차, 적중률
- CSV : data/live_vs_backtest_<YYYYMMDD>.csv
"""
import os
import sys
import argparse
from datetime import datetime
import pandas as pd
import numpy as np

from src.config_db import get_connection, get_db_path
from src.logger import get_logger

logger = get_logger('validate')


def _load_closed_positions():
    """positions 테이블에서 청산 완료(close*) 행만 추출."""
    conn = get_connection()
    try:
        df = pd.read_sql(
            """SELECT ticker, name, sector, market, quantity,
                      buy_price, buy_date, sell_price, sell_date,
                      close_reason, status
               FROM positions WHERE status LIKE 'closed%'""",
            conn,
        )
    except Exception as e:
        logger.error(f"positions 조회 실패: {e}")
        return pd.DataFrame()
    finally:
        conn.close()

    if df.empty:
        return df

    # 날짜 정규화
    df['buy_date']  = pd.to_datetime(df['buy_date'])
    df['sell_date'] = pd.to_datetime(df['sell_date'])
    df['buy_day']   = df['buy_date'].dt.normalize()
    df['holding_business_days'] = df.apply(
        lambda r: int(np.busday_count(r['buy_day'].date(), r['sell_date'].date()))
        if pd.notna(r['sell_date']) else None,
        axis=1,
    )
    df['realized_return'] = (df['sell_price'] - df['buy_price']) / df['buy_price']
    return df


def _load_backtest_predictions(market):
    """finrl_dataset_kr/us 에서 (tic, date, lgbm_prob, next_return) 추출."""
    table = 'finrl_dataset_kr' if market == 'korea' else 'finrl_dataset_us'
    conn = get_connection()
    try:
        df = pd.read_sql(
            f"SELECT date, tic AS ticker, lgbm_prob, next_return, sector FROM {table}",
            conn,
        )
    except Exception as e:
        logger.warning(f"{table} 조회 실패(스킵): {e}")
        return pd.DataFrame()
    finally:
        conn.close()

    if df.empty:
        return df
    df['date'] = pd.to_datetime(df['date'])
    return df


def _match_to_backtest(live_df, bt_df):
    """
    실거래 (ticker, buy_day) 를 백테스트 (ticker, date) 와 매칭.
    동일 날짜 우선, 없으면 직전 영업일까지 최대 3일 fallback.
    """
    if live_df.empty or bt_df.empty:
        return live_df.assign(bt_prob=np.nan, bt_expected_return=np.nan,
                              bt_match_date=pd.NaT)

    bt_df = bt_df.sort_values(['ticker', 'date'])
    rows = []
    for _, r in live_df.iterrows():
        cand = bt_df[(bt_df['ticker'] == r['ticker']) &
                     (bt_df['date']  <= r['buy_day'])]
        if cand.empty:
            rows.append({'bt_prob': np.nan, 'bt_expected_return': np.nan,
                         'bt_match_date': pd.NaT})
            continue
        latest = cand.iloc[-1]
        # 너무 오래된 매칭은 의미가 약함 (3영업일 초과면 NaN)
        if (r['buy_day'] - latest['date']).days > 5:
            rows.append({'bt_prob': np.nan, 'bt_expected_return': np.nan,
                         'bt_match_date': pd.NaT})
            continue
        rows.append({
            'bt_prob': float(latest['lgbm_prob']),
            'bt_expected_return': float(latest['next_return']),
            'bt_match_date': latest['date'],
        })
    return pd.concat(
        [live_df.reset_index(drop=True), pd.DataFrame(rows)], axis=1
    )


def _summary(df, title):
    """요약 통계 출력."""
    print(f"\n=== {title} ===")
    if df.empty:
        print("(거래 없음)")
        return

    n = len(df)
    realized = df['realized_return']
    expected = df['bt_expected_return']
    gap = (realized - expected).dropna()

    print(f"거래 수: {n}")
    print(f"실현수익 평균: {realized.mean()*100:+.2f}% | std: {realized.std()*100:.2f}%")
    print(f"승률(>0): {(realized > 0).mean()*100:.1f}%")
    if not expected.dropna().empty:
        print(f"백테스트 예상수익 평균: {expected.mean()*100:+.2f}%")
        print(f"GAP(실현-예상) 평균: {gap.mean()*100:+.3f}%  std: {gap.std()*100:.3f}%")
        print("  - 음수면 백테스트가 낙관적(슬리피지/세금/시그널 지연 등 비용 과소추정)")
        print("  - 양수면 보수적(실제가 더 좋음 → 거래 룰 안전마진 충분)")
    else:
        print("(매칭된 백테스트 예측이 없습니다 - 백테스트를 먼저 한 번 실행해 주세요)")

    by_reason = df.groupby('close_reason')['realized_return'].agg(['count', 'mean']).sort_values('count', ascending=False)
    if not by_reason.empty:
        print("\n청산 사유별:")
        for r, row in by_reason.iterrows():
            print(f"  {r:>14} : {int(row['count']):>3}건  평균 {row['mean']*100:+.2f}%")


def main(out_dir=None):
    live = _load_closed_positions()
    if live.empty:
        print("청산된 포지션이 없습니다. 모의투자를 며칠 더 운영한 뒤 다시 실행하세요.")
        return

    out_dir = out_dir or os.path.dirname(get_db_path())
    os.makedirs(out_dir, exist_ok=True)

    parts = []
    for mk in ['korea', 'usa']:
        sub = live[live['market'] == mk].copy()
        if sub.empty:
            continue
        bt = _load_backtest_predictions(mk)
        matched = _match_to_backtest(sub, bt)
        _summary(matched, f"[{mk}] 실거래 vs 백테스트")
        parts.append(matched)

    if not parts:
        return

    full = pd.concat(parts, ignore_index=True)
    out_path = os.path.join(
        out_dir, f"live_vs_backtest_{datetime.now().strftime('%Y%m%d')}.csv"
    )
    cols = ['market', 'sector', 'ticker', 'name',
            'buy_day', 'sell_date', 'holding_business_days',
            'buy_price', 'sell_price', 'realized_return',
            'bt_match_date', 'bt_prob', 'bt_expected_return',
            'close_reason']
    cols = [c for c in cols if c in full.columns]
    full[cols].to_csv(out_path, index=False, encoding='utf-8-sig')
    print(f"\n상세 CSV: {out_path}")


def _parse_args():
    p = argparse.ArgumentParser(description="실거래 vs 백테스트 비교 리포트")
    p.add_argument('--out', default=None, help="CSV 출력 디렉터리")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    main(out_dir=args.out)
