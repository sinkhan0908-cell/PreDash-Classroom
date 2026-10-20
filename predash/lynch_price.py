"""Latest dated daily closes with explicit public/KIS cross-checks."""
import math
import re
from datetime import date,datetime,time
from zoneinfo import ZoneInfo
from predash.official import DataError
from predash.kis import BrokerError


PRICE_VERSION=1

# A conservative app cutoff, after normal and commonly delayed regular sessions.
# This is not an exchange-calendar service; only dated API daily rows are used.
SAME_DAY_AFTER=time(16,40)


def latest(rows, today, code=None, include_today=False):
    candidates=[]
    for row in rows:
        if not isinstance(row,dict):continue
        try:
            if code is not None and str(row.get('srtnCd','')).removeprefix('A').zfill(6)!=code:continue
            raw=str(row.get('basDt',''))
            if not re.fullmatch(r'\d{8}',raw):continue
            day=date.fromisoformat(f'{raw[:4]}-{raw[4:6]}-{raw[6:]}')
            value=float(str(row.get('clpr','')).replace(',',''))
            if (day<today or (include_today and day==today)) and math.isfinite(value) and value>0:candidates.append((day,value))
        except (ValueError,TypeError):continue
    if not candidates:raise DataError('사용 가능한 일별 종가 미확인')
    day,value=max(candidates)
    if len({v for d,v in candidates if d==day})!=1:raise DataError('동일 거래일 종가 응답 불일치')
    return {'date':day.isoformat(),'close':value}


def collect(code,today,public=None,kis=None,at=None):
    at=at or datetime.now(ZoneInfo('Asia/Seoul'))
    if at.tzinfo is None:raise DataError('종가 조회 시각의 시간대 확인 필요')
    local_at=at.astimezone(ZoneInfo('Asia/Seoul'))
    include_today=local_at.date()==today and local_at.time()>=SAME_DAY_AFTER
    quotes={};errors={}
    for name,loader in (('public',public),('kis',kis)):
        if loader is None:
            errors[name]='연결 미설정';continue
        try:quotes[name]=latest(loader(code,today),today,code,include_today=include_today)
        except (DataError,BrokerError,ValueError,TypeError) as exc:errors[name]=str(exc)
    if not quotes:raise DataError('종가 확인 실패 · '+ ' · '.join(f'{k}: {v}' for k,v in errors.items()))
    chosen=max(quotes,key=lambda name:(quotes[name]['date'],name=='public'))
    quote={**quotes[chosen],'source':'공공데이터포털' if chosen=='public' else 'KIS 모의 일별 시세',
           'kind':'종가','fetched_at':local_at.isoformat(timespec='seconds'),
           'selection_policy':'newest_daily_close_public_on_same_date',
           'same_day_after_kst':'16:40'}
    if len(quotes)==2:
        status='date_mismatch' if quotes['public']['date']!=quotes['kis']['date'] else 'matched' if quotes['public']['close']==quotes['kis']['close'] else 'mismatch'
    else:status='single_source'
    quote['crosscheck']={'status':status,'selected':chosen,'quotes':quotes,'errors':errors,
        'scope':'서로 다른 제공처의 같은 날짜 응답 비교 · 거래소 원장 직접 검증과 구분'}
    return quote
