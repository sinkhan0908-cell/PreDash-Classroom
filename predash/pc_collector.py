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
        block = dart_xbrl.collect(provider, today, annual)
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
    print('PreDash PC 수집기: 공식 DART → 기존 Supabase')
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
    except (StorageError, DataError, ValueError):
        # Never echo exception bodies: third-party errors may contain request credentials.
        print('수집 또는 검증에 실패했습니다. 성공 자료로 교체하지 않았습니다.')
        print('입력값·DART 연결을 확인하세요. 저장 요청 중 통신이 끊겼다면 사이트에서 반영 여부를 확인하세요.')
        return 1
    except (KeyboardInterrupt, EOFError):
        print('\n입력을 취소했습니다.')
        return 1
