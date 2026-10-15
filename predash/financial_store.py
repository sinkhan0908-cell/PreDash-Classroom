"""Latest successful public Lynch input snapshots, source separated and CAS merged."""
import json
import math
import re
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo
from predash.cloud_store import StorageError,StorageConflict

FIELD='lynch_financial_snapshots'
CACHE_VERSION=1
CALCULATION_VERSION='lynch-4year-v1'
FORBIDDEN={'key','secret','token','authorization','appkey','appsecret','access_token','cano','account','account_number','quantity','positions','credentials'}


def now():return datetime.now(ZoneInfo('Asia/Seoul')).isoformat(timespec='seconds')

def timestamp(value):
    stamp=datetime.fromisoformat(value)
    if stamp.tzinfo is None:raise ValueError('timezone required')
    return stamp


def clean_snapshot(saved):
    if not isinstance(saved,dict) or not isinstance(saved.get('data'),dict):raise StorageError('재무자료 형식 확인 필요')
    data=saved['data']
    code=data.get('code','')
    source=saved.get('source','DART')
    if not isinstance(code,str) or not re.fullmatch(r'\d{6}',code) or source not in ('DART','KIS'):
        raise StorageError('저장할 종목·자료 출처를 확인할 수 없습니다.')
    try:timestamp(data['fetched_at'])
    except (KeyError,ValueError,TypeError):raise StorageError('원자료 수집 시각 확인 필요') from None
    if not isinstance(data.get('rows'),list) or any(not isinstance(r,dict) for r in data['rows']):raise StorageError('재무 행 형식 확인 필요')
    annual=[r for r in data.get('rows',[]) if r.get('metric') in ('기본 EPS','KIS EPS') and r.get('report_code')=='11011' and r.get('period_type')=='연간']
    if len(annual)!=5 or any(type(r.get('value')) not in (int,float) or not math.isfinite(r['value']) for r in annual):
        raise StorageError('5개 연간 EPS 수집이 완전하지 않아 이전 성공 저장본을 교체하지 않습니다.')
    years=[r.get('year') for r in annual]
    if any(type(y) is not int for y in years) or sorted(years)!=list(range(min(years),min(years)+5)):
        raise StorageError('연속 5개 연간 EPS가 아닙니다. 이전 저장본 유지')
    result={k:deepcopy(saved[k]) for k in ('data','quote','source','excluded_periods','validation_level') if k in saved}
    result['source']=source
    def inspect(value):
        if isinstance(value,dict):
            if any(str(k).lower() in FORBIDDEN for k in value):raise StorageError('공개 재무자료 외 항목이 있어 저장하지 않습니다.')
            for v in value.values():inspect(v)
        elif isinstance(value,list):
            for v in value:inspect(v)
    inspect(result)
    try:
        if len(json.dumps(result,ensure_ascii=False,allow_nan=False).encode())>500000:raise StorageError('종목 자료 크기 한도를 초과했습니다.')
    except (ValueError,TypeError):raise StorageError('자료의 숫자·JSON 형식을 확인하세요.') from None
    return result


def select_snapshot(payload,code):
    bucket=payload.get(FIELD,{})
    if not isinstance(bucket,dict) or bucket.get('version')!=CACHE_VERSION:return None
    if not isinstance(bucket.get('items'),dict):return None
    entry=bucket['items'].get(code,{})
    if not isinstance(entry,dict):return None
    choices=[]
    for source in ('DART','KIS'):
        candidate=entry.get(source)
        if not isinstance(candidate,dict):continue
        try:
            saved=clean_snapshot(candidate['snapshot'])
            if saved['data']['code']!=code or saved['source']!=source:continue
            choices.append((timestamp(saved['data']['fetched_at']),source,saved,candidate.get('stored_at')))
        except (StorageError,KeyError,ValueError,TypeError):continue
    if not choices:return None
    _,source,saved,stored_at=max(choices,key=lambda item:(item[0],item[1]=='DART'))
    attempts=entry.get('attempts',{})
    if not isinstance(attempts,dict):attempts={}
    saved['_storage']={'restored':True,'stored_at':stored_at,'calculation_version':CALCULATION_VERSION,'last_attempt':next((a for a in attempts.values() if isinstance(a,dict) and a.get('status')=='failed'),entry.get('last_attempt'))}
    return saved


def persist(client,code,saved=None,attempt_kind='financial',failed=False):
    cleaned=clean_snapshot(saved) if saved is not None else None
    if cleaned and cleaned['data']['code']!=code:raise StorageError('자료 종목코드 불일치')
    for _ in range(3):
        row=client.load()
        payload=deepcopy(row['payload'])
        bucket=payload.setdefault(FIELD,{'version':CACHE_VERSION,'items':{}})
        if bucket.get('version')!=CACHE_VERSION or not isinstance(bucket.get('items'),dict):raise StorageError('재무 저장 형식 버전 확인 필요')
        entry=bucket['items'].setdefault(code,{})
        if not isinstance(entry,dict):raise StorageError('종목 재무 저장 형식 확인 필요')
        if cleaned:
            source=cleaned['source'];old=entry.get(source,{}).get('snapshot')
            if old and timestamp(old['data']['fetched_at'])>timestamp(cleaned['data']['fetched_at']):
                raise StorageConflict('다른 기기에서 더 최근 재무자료를 저장했습니다. 최신 저장본을 보존합니다.')
            if old and cleaned.get('quote',{}).get('close') and old.get('quote',{}).get('close'):
                try:
                    if timestamp(old['quote']['fetched_at'])>timestamp(cleaned['quote']['fetched_at']):cleaned['quote']=deepcopy(old['quote'])
                except (KeyError,ValueError,TypeError):pass
            if old and not cleaned.get('quote',{}).get('close') and old.get('quote',{}).get('close'):
                cleaned['quote']={**deepcopy(old['quote']),'refresh_error':'최근 가격 조회 실패 · 이전 가격과 원래 기준일 유지'}
            entry[source]={'snapshot':cleaned,'stored_at':now(),'calculation_version':CALCULATION_VERSION}
        entry['last_attempt']={'at':now(),'kind':attempt_kind,'status':'failed' if failed else 'success'}
        entry.setdefault('attempts',{})[attempt_kind]=deepcopy(entry['last_attempt'])
        # Bound storage to latest 24 researched companies, retaining both providers per company.
        if len(bucket['items'])>24:
            oldest=min((c for c in bucket['items'] if c!=code),key=lambda c:bucket['items'][c].get('last_attempt',{}).get('at',''))
            bucket['items'].pop(oldest)
        version=row['version']+1
        result=client.request('PATCH',extra_headers={'Prefer':'return=representation'},params={'id':'eq.personal','version':'eq.'+str(row['version'])},json={'version':version,'payload':payload})
        if not result:continue
        if len(result)!=1 or result[0].get('id')!='personal' or result[0].get('version')!=version or result[0].get('payload')!=payload:
            raise StorageError('재무자료 저장 응답 확인 실패. 저장본을 다시 확인하세요.')
        return deepcopy(result[0])
    raise StorageConflict('동시 저장 충돌로 재무자료 저장 확인 실패. 화면 결과는 유지합니다.')
