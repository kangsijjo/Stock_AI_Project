from dotenv import load_dotenv
import os

load_dotenv()

ACTIVE_SECTOR = "반도체"

# 국내 섹터 목록
# 반도체, 2차전지, AI전력망, 방산, 조선, 바이오, 엔터, 금융, 자동차, 화학,
# 철강, 건설, 유통, 통신, 게임, 음식료, 의류, 부동산, 기계, 항공

# 미국 섹터 목록 (S&P500 기준)
# Information Technology, Health Care, Financials, Consumer Discretionary,
# Industrials, Communication Services, Consumer Staples, Energy,
# Real Estate, Materials, Utilities

START_DATE = '2015-01-01'

KRX_API_KEY = os.getenv('KRX_API_KEY')
# 뉴스 가중치 (0.0 = 뉴스 무시, 1.0 = 뉴스 100% 반영)
NEWS_WEIGHT = 0.5