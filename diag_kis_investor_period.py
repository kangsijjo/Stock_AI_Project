"""
KIS API 에 '기간 지정 가능한 투자자별 매매동향' endpoint 가 있는지 탐색.
30일 한도를 넘는 백필 가능성 확인용.

실행: python diag_kis_investor_period.py
"""
import json
import requests
from src.trader.kis_api import KISTrader


def try_call(trader, name, url_path, tr_id, params):
    print(f"\n========== {name} ==========")
    print(f"  TR_ID: {tr_id}  URL: {url_path}")
    url = f"{trader.base_url}{url_path}"
    headers = trader.get_headers(tr_id)
    try:
        res = requests.get(url, headers=headers, params=params, timeout=10)
        try:
            data = res.json()
        except Exception:
            print(f"  HTTP {res.status_code} - 파싱 실패  raw: {res.text[:200]}")
            return
        rt_cd = data.get('rt_cd', '')
        msg = data.get('msg1', data.get('msg_cd', ''))
        print(f"  rt_cd={rt_cd}  msg={msg}")
        if rt_cd == '0':
            for key in ('output', 'output1', 'output2'):
                if key in data:
                    out = data[key]
                    if isinstance(out, list) and out:
                        print(f"  [{key}] 행 수: {len(out)}  날짜 범위: "
                              f"{out[-1].get('stck_bsop_date', '?')} ~ "
                              f"{out[0].get('stck_bsop_date', '?')}")
                        print(f"  첫 행 키: {list(out[0].keys())}")
                    elif isinstance(out, dict):
                        keys = list(out.keys())
                        print(f"  [{key}] dict 키: {keys[:15]}")
        else:
            print(f"  [실패] {json.dumps(data, ensure_ascii=False)[:300]}")
    except Exception as e:
        print(f"  예외: {e}")


trader = KISTrader(mock=True)
if not trader.get_token():
    print("토큰 발급 실패")
    raise SystemExit(1)

TICKER = "005930"

# 후보1: 기존 inquire-investor 에 기간 파라미터 추가 시도
try_call(
    trader, "기존 + 기간 파라미터",
    "/uapi/domestic-stock/v1/quotations/inquire-investor",
    "FHKST01010900",
    {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": TICKER,
        "FID_INPUT_DATE_1": "20250101",
        "FID_INPUT_DATE_2": "20260516",
        "FID_PERIOD_DIV_CODE": "D",
    },
)

# 후보2: 일별 외국인기관 매매 (기간 지정형)
try_call(
    trader, "inquire-daily-foreign-trade",
    "/uapi/domestic-stock/v1/quotations/inquire-daily-foreign-trade",
    "FHKST01010900",
    {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": TICKER,
        "FID_INPUT_DATE_1": "20250101",
        "FID_INPUT_DATE_2": "20260516",
    },
)

# 후보3: 외국인 매매 추이
try_call(
    trader, "foreign-trading",
    "/uapi/domestic-stock/v1/quotations/inquire-foreign-investing-trend",
    "FHKST03010100",
    {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": TICKER,
        "FID_INPUT_DATE_1": "20250101",
        "FID_INPUT_DATE_2": "20260516",
        "FID_PERIOD_DIV_CODE": "D",
    },
)

# 후보4: 일별 시세 차트 (이건 OHLCV 인데, 일부 응답에 외국인 정보 포함 가능)
try_call(
    trader, "inquire-daily-itemchartprice (참고용)",
    "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
    "FHKST03010100",
    {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": TICKER,
        "FID_INPUT_DATE_1": "20250101",
        "FID_INPUT_DATE_2": "20260516",
        "FID_PERIOD_DIV_CODE": "D",
        "FID_ORG_ADJ_PRC": "0",
    },
)

print("\n=== 가이드 ===")
print("rt_cd=0 으로 성공 + 행 수가 30 보다 많은 후보가 있으면 그 endpoint 로")
print("기간 지정 백필이 가능합니다. 결과 그대로 붙여주세요.")
