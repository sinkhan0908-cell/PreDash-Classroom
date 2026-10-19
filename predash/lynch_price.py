"""Public closing-price priority and explicit same-day KIS cross-checks."""
import math
import re
from datetime import date,datetime
from zoneinfo import ZoneInfo
from predash.official import DataError
from predash.kis import BrokerError


def latest(rows, today, code=None):
    candidates=[]
    for row in rows:
        if not isinstance(row,dict):continue
        try:
            if code is not None and str(row.get('srtnCd','')).removeprefix('A').zfill(6)!=code:continue
            raw=str(row.get('basDt',''))
            if not re.fullmatch(r'\d{8}',raw):continue
            day=date.fromisoformat(f'{raw[:4]}-{raw[4:6]}-{raw[6:]}')
            value=float(str(row.get('clpr','')).replace(',',''))
            if day<today and math.isfinite(value) and value>0:candidates.append((day,value))
        except (ValueError,TypeError):continue
    if not candidates:raise DataError('이전 거래일 확정 종가 미확인')
    day,value=max(candidates)
    if len({v for d,v in candidates if d==day})!=1:raise DataError('동일 거래일 종가 응답 불일치')
    return {'date':day.isoformat(),'close':value}


def collect(code,today,public=None,kis=None):
    quotes={};errors={}
    for name,loader in (('public',public),('kis',kis)):
        if loader is None:
            errors[name]='연결 미설정';continue
        try:quotes[name]=latest(loader(code,today),today,code)
        except (DataError,BrokerError,ValueError,TypeError) as exc:errors[name]=str(exc)
    if not quotes:raise DataError('종가 확인 실패 · '+ ' · '.join(f'{k}: {v}' for k,v in errors.items()))
    chosen='public' if 'public' in quotes else 'kis'
    quote={**quotes[chosen],'source':'공공데이터포털' if chosen=='public' else 'KIS 모의 일별 시세',
           'kind':'종가','fetched_at':datetime.now(ZoneInfo('Asia/Seoul')).isoformat(timespec='seconds')}
    if len(quotes)==2:
        status='date_mismatch' if quotes['public']['date']!=quotes['kis']['date'] else 'matched' if quotes['public']['close']==quotes['kis']['close'] else 'mismatch'
    else:status='single_source'
    quote['crosscheck']={'status':status,'selected':chosen,'quotes':quotes,'errors':errors,
        'scope':'서로 다른 제공처의 같은 날짜 응답 비교 · 거래소 원장 직접 검증과 구분'}
    return quote
