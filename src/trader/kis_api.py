import requests
import os
import time
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from src.logger import get_logger

load_dotenv()
logger = get_logger('kis_api')

# 토큰 캐시 디렉터리 (DB 와 같은 data/ 폴더 사용)
_TOKEN_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'data'
)
# KIS 토큰은 발급 후 24시간 유효. 안전마진 1시간 두고 23시간 재사용.
_TOKEN_TTL_HOURS = 23

class KISTrader:
    def __init__(self, mock=True):
        self.mock = mock
        
        if mock:
            self.app_key    = os.getenv('KIS_MOCK_APP_KEY')
            self.app_secret = os.getenv('KIS_MOCK_APP_SECRET')
            self.account    = os.getenv('KIS_MOCK_ACCOUNT')
            self.base_url   = "https://openapivts.koreainvestment.com:29443"
        else:
            self.app_key    = os.getenv('KIS_APP_KEY')
            self.app_secret = os.getenv('KIS_APP_SECRET')
            self.account    = os.getenv('KIS_ACCOUNT')
            self.base_url   = "https://openapi.koreainvestment.com:9443"
        
        self.access_token = None
        mode = "모의투자" if mock else "실전투자"
        logger.info(f"KIS Trader 초기화 ({mode})")

    def _token_cache_path(self):
        os.makedirs(_TOKEN_DIR, exist_ok=True)
        suffix = 'mock' if self.mock else 'real'
        return os.path.join(_TOKEN_DIR, f'kis_token_{suffix}.json')

    def _load_cached_token(self):
        """캐시된 토큰이 23시간 안에 발급된 거면 재사용."""
        path = self._token_cache_path()
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            issued = datetime.fromisoformat(data['issued_at'])
            if datetime.now() - issued < timedelta(hours=_TOKEN_TTL_HOURS):
                return data['access_token']
        except Exception:
            return None
        return None

    def _save_cached_token(self, token):
        try:
            with open(self._token_cache_path(), 'w', encoding='utf-8') as f:
                json.dump({
                    'access_token': token,
                    'issued_at': datetime.now().isoformat(),
                }, f)
        except Exception as e:
            logger.warning(f"토큰 캐시 저장 실패(스킵): {e}")

    def get_token(self, force_refresh=False):
        """
        KIS Open API 의 토큰 발급은 1분당 1회 제한이 있다.
        파일 캐시(23시간)를 먼저 확인하고, 만료/강제재발급일 때만 API 호출.
        """
        if not force_refresh:
            cached = self._load_cached_token()
            if cached:
                self.access_token = cached
                logger.info("토큰 캐시 재사용 (만료 전)")
                return True

        url = f"{self.base_url}/oauth2/tokenP"
        headers = {"Content-Type": "application/json"}
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret
        }
        res = requests.post(url, headers=headers, json=body)
        data = res.json()

        if 'access_token' in data:
            self.access_token = data['access_token']
            self._save_cached_token(self.access_token)
            logger.info("토큰 발급 완료!")
            return True
        else:
            logger.error(f"토큰 발급 실패: {data}")
            return False

    def get_headers(self, tr_id):
        return {
            "Content-Type": "application/json",
            "authorization": f"Bearer {self.access_token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P"
        }

    def get_balance(self):
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        tr_id = "VTTC8434R" if self.mock else "TTTC8434R"
        headers = self.get_headers(tr_id)
        params = {
            "CANO": self.account,
            "ACNT_PRDT_CD": "01",
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "N",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }
        res = requests.get(url, headers=headers, params=params)
        data = res.json()
        
        if data.get('rt_cd') == '0':
            output2 = data.get('output2', [{}])[0]
            total_eval     = output2.get('tot_evlu_amt', '0')
            available_cash = output2.get('dnca_tot_amt', '0')
            logger.info(f"총 평가금액: {int(total_eval):,}원")
            logger.info(f"주문가능금액: {int(available_cash):,}원")
            return data
        else:
            logger.error(f"잔고 조회 실패: {data.get('msg1')}")
            return None

    def get_current_price(self, ticker):
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = self.get_headers("FHKST01010100")
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": ticker
        }
        res = requests.get(url, headers=headers, params=params)
        data = res.json()
        
        if data.get('rt_cd') == '0':
            price = int(data['output']['stck_prpr'])
            logger.info(f"{ticker} 현재가: {price:,}원")
            time.sleep(0.3)
            return price
        else:
            logger.error(f"현재가 조회 실패: {data.get('msg1')}")
            return None

    def buy(self, ticker, quantity, price=None):
        """매수 주문 (지정가)"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        tr_id = "VTTC0802U" if self.mock else "TTTC0802U"
        headers = self.get_headers(tr_id)

        if price is None:
            price = self.get_current_price(ticker)
            if price is None:
                logger.error(f"현재가 조회 실패: {ticker}")
                return False

        body = {
            "CANO": self.account,
            "ACNT_PRDT_CD": "01",
            "PDNO": ticker,
            "ORD_DVSN": "00",
            "ORD_QTY": str(quantity),
            "ORD_UNPR": str(price)
        }
        res = requests.post(url, headers=headers, json=body)
        data = res.json()

        if data.get('rt_cd') == '0':
            logger.info(f"매수 완료: {ticker} {quantity}주 @ {price:,}원")
            return True
        else:
            logger.error(f"매수 실패: {data.get('msg1')}")
            return False

    def sell(self, ticker, quantity, price=None):
        """매도 주문 (지정가)"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        tr_id = "VTTC0801U" if self.mock else "TTTC0801U"
        headers = self.get_headers(tr_id)

        if price is None:
            price = self.get_current_price(ticker)
            if price is None:
                logger.error(f"현재가 조회 실패: {ticker}")
                return False

        body = {
            "CANO": self.account,
            "ACNT_PRDT_CD": "01",
            "PDNO": ticker,
            "ORD_DVSN": "00",
            "ORD_QTY": str(quantity),
            "ORD_UNPR": str(price)
        }
        res = requests.post(url, headers=headers, json=body)
        data = res.json()

        if data.get('rt_cd') == '0':
            logger.info(f"매도 완료: {ticker} {quantity}주 @ {price:,}원")
            return True
        else:
            logger.error(f"매도 실패: {data.get('msg1')}")
            return False

    # ─────────────────────────────────────────────────────────────
    # 시장 스캐너용: 등락률 / 거래량 상위 종목 조회
    # 모의/실전 모두 지원되는 시세성 API (분당 호출 한도 안에서 사용).
    # ─────────────────────────────────────────────────────────────
    def get_top_change_rate(self, count=30, asc=False):
        """
        등락률 순위 조회.
        asc=False → 상승률 상위, True → 하락률 상위.
        반환: 리스트(dict) — 종목코드, 종목명, 현재가, 등락률, 누적거래량 등 포함.
        """
        url = f"{self.base_url}/uapi/domestic-stock/v1/ranking/fluctuation"
        headers = self.get_headers("FHPST01700000")
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_COND_SCR_DIV_CODE": "20170",
            "FID_INPUT_ISCD": "0000",
            "FID_RANK_SORT_CLS_CODE": "1" if asc else "0",
            "FID_INPUT_CNT_1": "0",
            "FID_PRC_CLS_CODE": "0",
            "FID_INPUT_PRICE_1": "",
            "FID_INPUT_PRICE_2": "",
            "FID_VOL_CNT": "",
            "FID_TRGT_CLS_CODE": "0",
            "FID_TRGT_EXLS_CLS_CODE": "0",
            "FID_DIV_CLS_CODE": "0",
            "FID_RSFL_RATE1": "",
            "FID_RSFL_RATE2": "",
        }
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5)
            data = res.json()
            if data.get('rt_cd') == '0':
                return data.get('output', [])[:count]
            logger.error(f"등락률 상위 조회 실패: {data.get('msg1')} ({data.get('msg_cd')})")
        except Exception as e:
            logger.error(f"등락률 상위 조회 예외: {e}")
        return []

    def get_investor_daily(self, ticker):
        """
        종목별 일자별 투자자별 매매동향 (최근 30 거래일).
        TR_ID: FHKST01010900
        반환: 리스트(dict) — stck_bsop_date, frgn_ntby_tr_pbmn(외국인 순매수금액),
              orgn_ntby_tr_pbmn(기관 순매수금액) 등 포함.
        """
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-investor"
        headers = self.get_headers("FHKST01010900")
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": ticker,
        }
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5)
            data = res.json()
            if data.get('rt_cd') == '0':
                return data.get('output', [])
            logger.error(f"투자자별 매매 조회 실패 {ticker}: {data.get('msg1')}")
        except Exception as e:
            logger.error(f"투자자별 매매 조회 예외 {ticker}: {e}")
        return []

    def get_top_volume(self, count=30):
        """거래량 상위. 반환: 리스트(dict)."""
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/volume-rank"
        headers = self.get_headers("FHPST01710000")
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_COND_SCR_DIV_CODE": "20171",
            "FID_INPUT_ISCD": "0000",
            "FID_DIV_CLS_CODE": "0",
            "FID_BLNG_CLS_CODE": "0",
            "FID_TRGT_CLS_CODE": "111111111",
            "FID_TRGT_EXLS_CLS_CODE": "000000",
            "FID_INPUT_PRICE_1": "0",
            "FID_INPUT_PRICE_2": "0",
            "FID_VOL_CNT": "0",
            "FID_INPUT_DATE_1": "0",
        }
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5)
            data = res.json()
            if data.get('rt_cd') == '0':
                return data.get('output', [])[:count]
            logger.error(f"거래량 상위 조회 실패: {data.get('msg1')} ({data.get('msg_cd')})")
        except Exception as e:
            logger.error(f"거래량 상위 조회 예외: {e}")
        return []


if __name__ == "__main__":
    trader = KISTrader(mock=True)
    trader.get_token()
    trader.get_balance()