"""
DB positions 테이블의 orphan 포지션 정리 + 손익 리포트.

orphan 이란
-----------
positions 테이블엔 'open' 인데 KIS 계좌엔 실제 잔고가 없는 행. 그대로 두면
intraday_monitor 가 매 1분마다 손절 시도 → 매도 실패 → DB close 안 됨 →
무한 루프가 된다.

이 스크립트가 하는 일
---------------------
1) status='open' 인 행 중 KIS 잔고에 없는 종목을 'closed_orphan_initial' 로 정리
   - 현재가를 sell_price 로 스냅샷 (cleanup 시점 가상 청산가)
2) 이전에 정리됐지만 sell_price=buy_price 였던(P/L=0 으로 잘못 기록된) orphan 도
   재스냅샷
3) 종목별 손익 + 총 손익 출력

손익의 의미
-----------
이 P/L 은 cleanup 시점 현재가 기준 '가상' 손익. 실제 KIS 매도가 일어난 게
아니므로 실현손익이 아니다. 자본/현금 잔고에 영향 없음. 단지 "그 시점에
매도했다면 얼마였을지" 의 기록.

사용
----
    python cleanup_orphan_positions.py            # 모의계좌
    python cleanup_orphan_positions.py --real     # 실전계좌 (주의)
"""
import argparse
import sys
from datetime import datetime

from src.config_db import get_connection
from src.logger import get_logger
from src.trader.kis_api import KISTrader
from src.trader.position_manager import init_position_table

logger = get_logger('cleanup_orphan')


def cleanup(mock=True):
    # 구버전 DB 컬럼 마이그레이션 트리거
    init_position_table()

    trader = KISTrader(mock=mock)
    if not trader.get_token():
        logger.error("토큰 발급 실패 - 종료")
        return 1

    holdings = trader.get_holdings()
    if holdings is None:
        logger.error("KIS 잔고 조회 실패 - 안전을 위해 정리 안 함")
        return 2

    logger.info(f"KIS 실제 보유종목 {len(holdings)}개: {sorted(holdings) if holdings else '[]'}")

    conn = get_connection()
    cur = conn.cursor()

    # 대상 선정:
    #   (a) status='open' 인데 KIS 잔고에 없음  → 신규 orphan, status 도 변경
    #   (b) status LIKE 'closed_orphan%' 이고 sell_price=buy_price → 재스냅샷만
    rows = cur.execute(
        "SELECT id, ticker, name, buy_price, quantity, buy_date, status, sell_price "
        "FROM positions "
        "WHERE status='open' "
        "   OR (status LIKE 'closed_orphan%' AND sell_price = buy_price)"
    ).fetchall()

    targets = []
    for pos_id, ticker, name, buy_price, qty, buy_date, status, sell_price in rows:
        if status == 'open':
            if ticker not in holdings:
                targets.append((pos_id, ticker, name, buy_price, qty, buy_date, 'new'))
        else:
            targets.append((pos_id, ticker, name, buy_price, qty, buy_date, 'resnap'))

    if not targets:
        logger.info("정리 대상 없음 (orphan 없음)")
        conn.close()
        return 0

    logger.info(f"정리 대상 {len(targets)}개 - 현재가 스냅샷 시작")

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    display_rows = []
    total_pnl_amount = 0.0
    total_buy_amount = 0.0

    for pos_id, ticker, name, buy_price, qty, buy_date, kind in targets:
        current_price = trader.get_current_price(ticker)
        if current_price is None:
            logger.warning(f"  {name}({ticker}) 현재가 조회 실패 - 스킵")
            continue

        pnl_pct = (current_price - buy_price) / buy_price * 100
        pnl_amt = (current_price - buy_price) * qty
        total_pnl_amount += pnl_amt
        total_buy_amount += buy_price * qty

        if kind == 'new':
            cur.execute(
                "UPDATE positions "
                "SET status='closed_orphan_initial', sell_price=?, sell_date=?, "
                "    close_reason='orphan_cleanup' "
                "WHERE id=?",
                [current_price, now, pos_id]
            )
        else:
            # 재스냅샷: status 는 그대로, sell_price/sell_date 만 갱신
            cur.execute(
                "UPDATE positions SET sell_price=?, sell_date=? WHERE id=?",
                [current_price, now, pos_id]
            )

        display_rows.append({
            'name': name, 'ticker': ticker, 'qty': qty,
            'buy_date': buy_date[:10] if buy_date else '',
            'buy_price': buy_price,
            'sell_date': now[:10],
            'sell_price': current_price,
            'pnl_pct': pnl_pct, 'pnl_amt': pnl_amt,
        })

    conn.commit()
    conn.close()

    # 결과 표 출력
    print()
    print("=" * 100)
    print(f"{'종목':<14}{'코드':<8}{'수량':>6}  {'매수일':<11}{'매도일':<11}"
          f"{'매수가':>9}{'매도가':>9}{'손익%':>9}{'손익(원)':>14}")
    print("-" * 100)
    for r in display_rows:
        print(f"{r['name']:<14}{r['ticker']:<8}{r['qty']:>6}  "
              f"{r['buy_date']:<11}{r['sell_date']:<11}"
              f"{r['buy_price']:>9,.0f}{r['sell_price']:>9,.0f}"
              f"{r['pnl_pct']:>+8.2f}%{r['pnl_amt']:>+14,.0f}")
    print("-" * 100)
    if total_buy_amount > 0:
        total_pct = total_pnl_amount / total_buy_amount * 100
        print(f"{'합계':<14}{'':<8}{'':>6}  {'':<11}{'':<11}"
              f"{total_buy_amount:>9,.0f}{'':>9}"
              f"{total_pct:>+8.2f}%{total_pnl_amount:>+14,.0f}")
    print("=" * 100)
    print()
    print("[참고] 위 손익은 cleanup 시점 현재가 기준의 '가상' 손익입니다.")
    print("       orphan 은 실제 KIS 매도가 발생하지 않았으므로 실현손익이 아니며,")
    print("       자본/현금 잔고에는 영향 없습니다.")
    print()

    logger.info(
        f"정리 완료: {len(display_rows)}건, "
        f"가상 P/L 합계 {total_pnl_amount:+,.0f}원"
    )
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument('--real', action='store_true', help='실전계좌 (주의)')
    args = p.parse_args()
    sys.exit(cleanup(mock=not args.real))
