# Supabase 관심종목 연결 · 첫 단계

이번 단계는 관심종목 코드·이름의 저장/복원입니다. 기존 personal.payload의 journal/runs 및 알 수 없는 키는 보존하며 투자일지·분석결과·API 캐시 자동 저장은 하지 않습니다. 종목별 추가 필드도 남아 있는 종목에서는 보존합니다.

## 사용자 설정

1. Supabase SQL Editor에서 predash/schema.sql을 실행합니다. public.stock_dash_state 테이블과 personal 행을 확인합니다. 새 테이블이나 추가 SQL 함수는 필요하지 않습니다.
2. Streamlit Settings → Secrets에 아래를 추가합니다. 값은 채팅·GitHub에 넣지 않습니다.

```toml
SUPABASE_URL = "https://내프로젝트.supabase.co"
SUPABASE_SECRET_KEY = "서버용 Secret key"
```

교재의 legacy 키를 사용한다면 SUPABASE_SECRET_KEY 대신 SUPABASE_SERVICE_ROLE_KEY로 설정합니다. 둘 중 하나면 됩니다. 두 가지가 모두 있으면 새 Secret key가 우선입니다. anon/publishable 키는 거부합니다. 새 Secret key는 apikey 헤더로만 전송하고 JWT Bearer로 넣지 않습니다.

3. Save 후 앱 재시작, APP_PASSWORD로 로그인합니다. 비밀번호 없는 공개 모드에서는 DB에 접속하지 않습니다.
4. 09 데이터 연결 → Supabase 관심종목 저장 → 연결 확인·목록 다시 불러오기.
5. 02 관심종목에서 한 종목을 저장하고, Supabase Table Editor의 personal.payload.stocks 및 증가한 version을 확인합니다.
6. 다른 브라우저·기기에서 동일 앱에 로그인하고 같은 목록을 확인합니다.

## 동작 및 한계

- 로그인 후 세션 최초 1회 읽습니다. 추가·삭제·백업 복원 시 서버 저장을 요청합니다. 다른 기기의 변경은 다시 불러오기를 통해 반영합니다.
- DB가 비어 있고 현재 브라우저에 기존 목록이 있으면 자동으로 버리지 않습니다. 09 데이터 연결에서 '현재 관심종목을 클라우드에 저장'을 눌러 처음 저장합니다.
- 저장은 현재 version을 조건으로 PATCH합니다. 버전이 달라지면 충돌로 중단합니다. 현재 화면 목록을 유지하고 미저장 경고를 표시합니다. 저장 실패 후 자동 무한 재시도/덮어쓰기를 하지 않습니다.
- '목록 다시 불러오기'는 현재 화면 목록을 원격 목록으로 바꿉니다. 미저장 목록은 먼저 백업합니다.
- 기존 stocks 구조가 code/name 형식과 다르거나 8개를 초과하면 자동 이전을 중단합니다. 기존 자료를 임의로 잘라 저장하지 않습니다.
- timeout=(5,15), 리디렉션 금지, 프로젝트 API URL 검증, 키·응답본문·네트워크 예외 원문 비노출.
- 프로젝트 URL/서버키는 서버에서만 사용합니다. 브라우저의 URL·분석 내려받기에 포함하지 않습니다. 키가 설정됐다는 사실만으로 연결 성공을 표시하지 않습니다.
- DB 통신 성공은 실제 사용자 프로젝트 설정 후 읽기·쓰기·다른 기기 확인까지 검증해야 합니다. 자동 테스트는 해당 실서버 검증을 대신하지 않습니다.

공식 참고: https://supabase.com/docs/guides/getting-started/api-keys

## 린치 재무자료 확장

최신 성공 입력자료의 자동 저장·복원이 추가되었습니다. 새 SQL이나 키 설정은 필요하지 않습니다. 동작 범위와 실제 확인 순서는 SUPABASE-FINANCIAL-CACHE.md를 참고하세요. 투자일지와 전체 분석 이력 자동 저장은 여전히 포함하지 않습니다.
