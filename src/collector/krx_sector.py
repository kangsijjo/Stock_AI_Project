import requests
import pandas as pd
import sqlite3
import os
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.path.join(os.path.dirname(__file__), '../../data/stock.db')
KRX_API_KEY = os.getenv('KRX_API_KEY')

def get_connection():
    return sqlite3.connect(DB_PATH)

def fetch_krx_sectors():
    """KRX API로 전체 종목 섹터 정보 가져오기"""
    url = "https://openapi.krx.co.kr/svc/apis/sto/stk_isu_base_info"
    headers = {'AUTH_KEY': KRX_API_KEY}
    params = {'basDd': '20260507'}

    try:
        res = requests.get(url, headers=headers, params=params, timeout=10)
        data = res.json()
        df = pd.DataFrame(data['output'])
        print(f"KRX 종목 정보 {len(df)}개 가져옴")
        print(df[['ISU_SRT_CD', 'ISU_NM', 'SECT_TP_NM']].head(10))
        return df
    except Exception as e:
        print(f"KRX API 실패: {e}")
        print(f"응답 내용: {res.text[:200]}")
        return None

def update_sectors():
    """DB의 korea_stocks 섹터 정보 업데이트"""
    df = fetch_krx_sectors()
    if df is None:
        return

    conn = get_connection()
    for _, row in df.iterrows():
        ticker = row['ISU_SRT_CD']
        sector = row['SECT_TP_NM']
        conn.execute(
            "UPDATE korea_stocks SET sector=? WHERE ticker=?",
            [sector, ticker]
        )
    conn.commit()
    conn.close()
    print("섹터 정보 업데이트 완료!")

if __name__ == "__main__":
    fetch_krx_sectors()