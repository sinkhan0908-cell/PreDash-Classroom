# KIS 모의 재무 조회 테스트

09 데이터 연결 → KIS 모의 재무 조회 테스트 → 종목코드 → 실행.

- 모의투자 서버만 사용하며 실전 키로 전환하지 않습니다. 완성된 모의 App Key/Secret 쌍만 한 출처에서 선택합니다. 계좌번호는 불필요합니다.
- 토큰 발급 및 두 GET 엔드포인트만 허용합니다. 잔고·주문 요청은 차단합니다.
- 현재가: /uapi/domestic-stock/v1/quotations/inquire-price / FHKST01010100. 현재가·EPS·PER만 추출합니다. EPS 대상 연도는 이 응답에서 확정하지 않습니다.
- 연간 재무비율: /uapi/domestic-stock/v1/finance/financial-ratio / FHKST66430300 / FID_DIV_CLS_CODE=0. 결산 년월·EPS·연속 페이지 표지만 확인합니다. 최초 응답만 검사하고 5년치·연결기준·주당단위 검증 완료로 처리하지 않습니다.
- 모의 키에서 재무비율이 지원되는지는 실제 버튼 실행 결과로 확인합니다. 실패 코드 하나만으로 미지원 또는 키 오류를 확정하지 않습니다.
- 각 API는 독립 결과이며 첫 실패가 두 번째 검사를 막지 않습니다. 인증 실패 시 추가 요청을 중단합니다. GET 사이에 1.1초 간격을 둡니다.
- 화면/다운로드에는 토큰·키·계좌·증권사 원문 메시지를 포함하지 않습니다. 키/토큰은 기존 방식처럼 서버 세션에만 보관합니다.
- 기존 린치 계산이나 DART 대체 정책은 변경하지 않습니다. 검증 전 KIS 자료로 자동 계산하지 않습니다.

공식 샘플 확인일: 2026-10-15
https://github.com/koreainvestment/open-trading-api/tree/main/examples_llm/domestic_stock/inquire_price
https://github.com/koreainvestment/open-trading-api/tree/main/examples_llm/domestic_stock/finance_financial_ratio
