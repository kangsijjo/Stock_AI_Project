"""
KIS Open Trading API 의 '주식 투자자별 매매동향' 응답 형태 확인.

후보 endpoint/TR_ID 들을 차례로 시도해서:
  - 어느 호출이 성공(rt_cd=0)하는지
  - 응답 필드명이 무엇인지 (외국인/기관 매매금액 등)
  - 데이터가 며칠치 제공되는지

응답 출력을 그대로 보여주시면 supply_demand.py 를 정확히 재작성합니다.

실행: python diag_kis_investor.py
"""
import json
import requests
from src.trader.kis_api import KISTrader


def try_call(trader, name, url_path, tr_id, params):
    print(f"\n========== {name} ==========")
    print(f"  TR_ID: {tr_id}")
    print(f"  URL  : {url_path}")
    url = f"{trader.base_url}{url_path}"
    headers = trader.get_headers(tr_id)
    try:
        res = requests.get(url, headers=headers, params=params, timeout=10)
        try:
            data = res.json()
        except Exception:
            print(f"  HTTP {res.status_code} - JSON 파싱 실패")
            print(f"  raw: {res.text[:300]}")
            return

        rt_cd = data.get('rt_cd', '')
        msg = data.get('msg1', data.get('msg_cd', ''))
        print(f"  rt_cd={rt_cd}  msg={msg}")

        if rt_cd == '0':
            for key in ('output', 'output1', 'output2'):
                if key in data:
                    out = data[key]
                    if isinstance(out, list) and out:
                        print(f"  [{key}] 행 수: {len(out)}")
                        print(f"  [{key}] 첫 행 필드:")
                        for k, v in out[0].items():
                            print(f"    {k} = {v}")
                        if len(out) > 1:
                            print(f"  [{key}] 두번째 행:")
                            for k, v in out[1].items():
                                print(f"    {k} = {v}")
                    elif isinstance(out, dict):
                        print(f"  [{key}] dict:")
                        for k, v in out.items():
                            print(f"    {k} = {v}")
                    else:
                        print(f"  [{key}] = {out}")
        else:
            print(f"  [실패] full response: {json.dumps(data, ensure_ascii=False)[:400]}")
    except Exception as e:
        print(f"  예외: {e}")


trader = KISTrader(mock=True)
if not trader.get_token():
    print("토큰 발급 실패. 1분 후 재시도하거나 .env 의 KIS_MOCK_* 확인.")
    raise SystemExit(1)

TICKER = "005930"  # 삼성전자

# 후보 1: 종목별 투자자별 매매동향 (일별)
try_call(
    trader,
    "후보1: inquire-investor (FHKST01010900)",
    "/uapi/domestic-stock/v1/quotations/inquire-investor",
    "FHKST01010900",
    {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": TICKER,
    },
)

# 후보 2: 종목별 외국인 매매 동향
try_call(
    trader,
    "후보2: foreign-trade (FHKST01010900 alt)",
    "/uapi/domestic-stock/v1/quotations/foreign-search-info",
    "HHDFS76200100",
    {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": TICKER,
    },
)

# 후보 3: 일별 외국인기관 매매상위 (랭킹형)
try_call(
    trader,
    "후보3: ranking foreign-institution",
    "/uapi/domestic-stock/v1/ranking/foreign-institution-trans",
    "FHPTJ04400000",
    {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD_1": "0000",
        "FID_INPUT_ISCD_2": "0000",
        "FID_INPUT_ISCD_3": "0000",
    },
)

# 후보 4: 종목별 일자별 외국인 매매현황 (오늘+과거)
try_call(
    trader,
    "후보4: daily-foreign-trade",
    "/uapi/domestic-stock/v1/quotations/inquire-investor",
    "FHPTJ04400000",
    {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": TICKER,
    },
)

print("\n\n=== 분석 가이드 ===")
print("rt_cd=0 으로 성공한 후보의 응답 필드를 정확한 코드 작성에 사용합니다.")
print("실패하면 KIS API 포탈(apiportal.koreainvestment.com)의 '주식 시세' 카테고리에서")
print("'투자자별 매매현황' 또는 '외국인 매매' 관련 API 명세 확인이 필요합니다.")
