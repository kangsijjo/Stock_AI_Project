import requests
import os
import time
from dotenv import load_dotenv
from src.logger import get_logger

load_dotenv()
logger = get_logger('kis_api')

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

    def get_token(self):
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

if __name__ == "__main__":
    trader = KISTrader(mock=True)
    trader.get_token()
    trader.get_balance()