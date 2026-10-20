"""Interactive PC bridge. Credentials remain in process memory only."""
from copy import deepcopy
from datetime import datetime
from getpass import getpass
import re
from zoneinfo import ZoneInfo
from predash.cloud_store import CloudStore, StorageError
from predash.financial_store import select_snapshot, clean_snapshot, persist
from predash.official import Official, DataError
from predash.lynch import collect_lynch
from predash import ttm, dart_xbrl, pharma_ir


# Only repository-authored literal messages may be shown; never raw server responses.
SAFE_REASONS = ('DART XBRL ZIP·XML 형식 확인 필요', 'DART XBRL 압축 크기 한도 초과', 'DART XBRL 압축 해제 한도 초과', 'DART XBRL 인스턴스 미확인', 'DART XBRL과 공식 IR 연간 EPS 불일치 · 정정 여부 확인 필요', 'DART 공시 목록 기업 식별 불일치', 'DART 기업 목록 응답을 읽지 못했습니다. 정상 ZIP·상장기업 목록인지 확인이 필요하며, 키 오류로 단정할 수 없습니다.', 'DART 기업개황: JSON 조회 실패 후 XML 응답도 읽지 못했습니다.', 'DART 기업개황의 고유번호가 요청과 일치하지 않습니다.', 'DART 기업개황의 기업명 또는 결산월이 누락됐습니다. 추정하지 않고 중단합니다.', 'DART 기업개황의 기업명·종목코드·고유번호가 등록 정보와 일치하지 않습니다.', 'DART 기업개황의 기업명·종목코드·고유번호가 등록 정보와 일치하지 않습니다. 재무 조회를 중단합니다.', 'DART 보고서명·대상 기간 불일치', 'DART 응답 형식 오류', 'DART 인증키 형식을 확인하세요. 40자리 키가 필요합니다.', 'DART 전년 연간 보고서 미확인', 'DART 접속 확인 시간 초과. 현재 앱 서버가 DART 응답을 받지 못해 재무 분석을 중단했습니다.', 'DART 접속 확인 실패. 재무 분석을 중단했습니다.', 'DART 접수번호 확인 필요', 'DART 정기공시 목록 추가 페이지 미확인', 'DART 최근 완료 기간 미확인', 'DART 최근 정기공시 목록 미확인', 'SUPABASE_URL은 https://프로젝트.supabase.co 형식이어야 합니다.', 'Supabase 통신·응답 확인 실패. 저장 요청이었다면 반영 여부를 다시 불러와 확인하세요.', 'TTM 재무자료 계산 검증 실패', 'XBRL TTM 기간·순이익·주식수 대조 실패', 'XBRL 기간 식별자 중복', 'XBRL 기업 식별자가 혼재합니다.', 'XBRL 보고기간·접수일 불일치', 'XBRL 순이익·주식수·EPS 대조 불일치', 'XBRL 연결 보통주 기본 EPS 계정·기간·단위 누락 또는 불일치', 'XBRL 외부 선언 미지원', 'empty directory', 'personal 행이 없습니다. schema.sql을 실행하세요.', '공공데이터포털 일별 시세 승인·인증 오류', '공공데이터포털 일별 시세 응답을 읽지 못했습니다.', '공공데이터포털 종목 검색 응답을 읽지 못했습니다.', '공공데이터포털 종목 검색: 시세 서비스 승인과 인증키를 확인하세요.', '기준일 이후 XBRL 접수번호', '다른 기기에서 자료가 변경됐습니다. 클라우드를 다시 불러온 뒤 수정해 주세요. 현재 목록은 화면에 유지합니다.', '독립적인 공식 IR 기업 식별 자료 필요', '동시 저장 충돌이 발생했습니다. 현재 목록을 유지합니다. 클라우드 다시 불러오기가 필요합니다.', '동일 연결/별도 기준의 3개년 보고서가 부족합니다. 사업연도를 바꿔보세요.', '비교 가능한 최근 분기·반기 누적 실적을 찾지 못했습니다.', '상장 종목코드를 찾지 못했습니다.', '서버용 Secret key 또는 legacy service_role 키가 필요합니다. anon·publishable 키는 사용할 수 없습니다.', '시세 API 승인·인증 오류', '시세 응답 형식 오류', '저장 응답이 요청과 일치하지 않습니다. 클라우드를 다시 불러와 확인하세요.', '저장된 stocks 배열 형식을 확인하세요.', '저장소의 version·payload 구조를 확인하세요.', '종목코드는 숫자 6자리로 입력하세요.', '종목코드는 숫자 6자리여야 합니다.', '최근 10일 안에 시세가 없습니다.', '최근 결산 보고서를 찾지 못했습니다.', '최신 저장본이 달라졌습니다. 클라우드를 다시 조회하세요.', '클라우드 종목 형식이 현재 앱과 다릅니다. 원본을 보존하고 불러오기를 중단합니다.', '클라우드 종목이 현재 앱의 8개 한도를 넘습니다. 자동으로 잘라 저장하지 않습니다.')

def diagnostic(exc):
    message = str(exc)
    if message in SAFE_REASONS:
        return "원인: " + message
    if isinstance(exc, DataError):
        if "초과" in message or "timeout" in message.lower():
            return "원인 [DART_TIMEOUT]: DART 응답 시간이 초과됐습니다."
        if "TLS" in message:
            return "원인 [DART_TLS]: DART 보안 연결에 실패했습니다."
        if "연결" in message:
            return "원인 [DART_CONNECT]: DART 서버 연결에 실패했습니다."
        return "원인 [DART_API]: DART API 응답·인증·이용 한도를 확인해야 합니다."
    return "원인 [UNRECOGNIZED]: 알려진 오류 유형이 아닙니다. 마지막 진행 문구를 함께 알려주세요."


def collect_and_save(client, provider, code, today):
    if not re.fullmatch(r'\d{6}', code):
        raise ValueError('종목코드는 숫자 6자리로 입력하세요.')
    previous = select_snapshot(client.load()['payload'], code)
    # Live company identity must succeed before any write.
    print('DART 회사 식별 확인 중…')
    provider.corp(code)
    if code == '214450' and previous:
        saved = deepcopy(previous)
        annual = saved.get('ttm', {})
        if annual.get('annual_eps_status') != 'success':
            annual = pharma_ir.collect(today)
        print('DART 공시 목록·원문 XBRL 검증 중…')
        block = dart_xbrl.collect(provider, today, annual, progress=print)
        block['collector_version'] = ttm.COLLECTOR_VERSION
    else:
        data = collect_lynch(provider, code, today)
        saved = {'data': data, 'source': 'DART', 'quote': (previous or {}).get('quote', {})}
        block = ttm.collect(provider, code, today)
    if block.get('status') != 'success':
        raise ValueError(block.get('reason') or 'TTM 공식 자료 검증 실패')
    # A synthetic quote validates financial inputs independently of stale market prices.
    checked = ttm.calculate(block, {'close': 1, 'date': today.isoformat(), 'source': 'validation'}, today)
    if checked['eps'] is None:
        raise ValueError('TTM 재무자료 계산 검증 실패')
    saved['ttm'] = block
    clean_snapshot(saved)
    print('재무 검증 완료 · Supabase 저장 중…')
    committed = persist(client, code, saved, attempt_kind='ttm')
    restored = select_snapshot(committed['payload'], code)
    if not restored or restored.get('ttm') != block:
        raise StorageError('최신 저장본이 달라졌습니다. 클라우드를 다시 조회하세요.')
    return checked


def main():
    print('PreDash PC 수집기 v2: 공식 DART → 기존 Supabase')
    print('키는 이 창에서만 입력하며 파일에 저장하지 않습니다. 입력 중 글자가 보이지 않습니다.')
    try:
        url = input('SUPABASE_URL: ').strip().rstrip('/')
        secret = getpass('Supabase Secret key / service_role: ').strip()
        dart_key = getpass('DART_CRTFC_KEY: ').strip()
        if not re.fullmatch(r'[A-Za-z0-9]{40}', dart_key):
            raise ValueError('DART 인증키 형식을 확인하세요. 40자리 키가 필요합니다.')
        code = input('종목코드 [214450]: ').strip() or '214450'
        print('조회·검증 중입니다. 잠시 기다려 주세요.')
        checked = collect_and_save(CloudStore(url, secret), Official(dart_key=dart_key, price_key=''), code,
                                   datetime.now(ZoneInfo('Asia/Seoul')).date())
        print(f"Supabase 저장 성공: {code} / TTM EPS {checked['eps']:,.2f}원")
        print('사이트 고급 설정에서 클라우드 연결 확인 · 목록 다시 불러오기를 눌러 주세요.')
        return 0
    except (StorageError, DataError, ValueError) as exc:
        print(diagnostic(exc))
        print('수집 또는 검증에 실패했습니다. 성공 자료로 교체하지 않았습니다.')
        print('입력값·DART 연결을 확인하세요. 저장 요청 중 통신이 끊겼다면 사이트에서 반영 여부를 확인하세요.')
        return 1
    except (KeyboardInterrupt, EOFError):
        print('\n입력을 취소했습니다.')
        return 1
