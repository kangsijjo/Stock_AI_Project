# Stock AI Project

AI 기반 주식 자동매매 시스템 (한국 + 미국)

## 시스템 구조


## 주요 기능

- 한국(KOSPI/KOSDAQ) + 미국(S&P500) 전체 종목 자동 수집
- 네이버 금융 기반 한국 섹터 분류
- FinBERT 기반 한국어/영어 뉴스 감성분석
- LightGBM 기반 5일 후 상승확률 예측
- SHAP 기반 AI 예측 근거 설명
- 한국투자증권 API 연동 모의/실전 자동매매
- 손절(5%) / 익절(10%) 자동 관리
- 전체 섹터 스캔 후 TOP3 종목 자동 매수

## 설치 방법

```bash
git clone https://github.com/kangsijjo/Stock_AI_Project.git
cd Stock_AI_Project
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## 환경변수 설정

`.env` 파일 생성:


## 사용 방법

### 데이터 수집
```bash
python -m src.collector.main_collector
```

### 거시지표 수집
```bash
python -m src.collector.macro
```

### 섹터별 분석 (메인 메뉴)
```bash
python main.py
```

### 전체 섹터 스캔
```bash
python scheduler.py scan
```

### 자동매매 (모의투자)
```bash
python -m src.trader.auto_trader
```

### 예측 근거 분석
```bash
python -m src.models.explain
```

### 스케줄러 시작
```bash
python scheduler.py
```

## 스케줄

| 시간 | 작업 |
|------|------|
| 매일 06:30 | 전체 종목 주가 업데이트 |
| 매일 06:50 | 전체 섹터 스캔 |
| 매일 08:00 | 한국주식 자동매매 |
| 매일 22:20 | 미국장 전 스캔 |
| 매일 22:30 | 미국주식 자동매매 |
| 매주 일요일 07:00 | 전체 재학습 |

## 섹터 목록

### 한국
반도체, 방산, 조선, 2차전지, 바이오, 엔터, 제약, 자동차, 게임, 소프트웨어 등

### 미국 (S&P500)
Information Technology, Financials, Health Care, Industrials, Energy 등

## 모의투자 기준

실전 투자 전 최소 기준:

| 항목 | 기준 |
|------|------|
| 운영 기간 | 1~3개월 |
| 승률 | 55% 이상 |
| MDD | 20% 이하 |
| 샤프비율 | 0.5 이상 |

## 주의사항

- 이 시스템은 투자 참고용이며 투자 손실에 대한 책임은 본인에게 있습니다
- 실전 투자 전 반드시 모의투자로 충분히 검증하세요
- 소액부터 시작하세요