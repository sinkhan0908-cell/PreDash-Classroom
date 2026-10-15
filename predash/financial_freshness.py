"""Bounded provider change checks. Unknown responses never mean unchanged."""
import hashlib
import json
import re
from datetime import timedelta
from predash.financial_store import clean_snapshot,timestamp
from predash.cloud_store import StorageError
from predash.company_codes import KNOWN_COMPANIES
from predash.kis_probe import run_probe,RATIOS
from predash.lynch_kis import build_reference


def fingerprint(saved):
    clean=clean_snapshot(saved)
    raw=json.dumps({'source':clean['source'],'data':clean['data']},sort_keys=True,ensure_ascii=False,allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def due(saved,record,at):
    if not isinstance(record,dict) or record.get('fingerprint')!=fingerprint(saved):return True
    try:age=(timestamp(at)-timestamp(record['checked_at'])).total_seconds()
    except (KeyError,ValueError,TypeError):return True
    return age<0 or age >= (900 if record.get('status')=='failed' else 21600)


def check_dart(provider,saved,today):
    code=saved['data']['code']
    corp=KNOWN_COMPANIES.get(code,{}).get('corp_code') or provider.corp(code)
    original=timestamp(saved['data']['fetched_at']).date()
    known={str(r.get('receipt')) for r in saved['data']['rows'] if r.get('receipt')}
    payload=provider.dart('list.json',corp_code=corp,bgn_de=(original-timedelta(days=7)).strftime('%Y%m%d'),
        end_de=today.strftime('%Y%m%d'),pblntf_ty='A',last_reprt_at='N',sort='date',sort_mth='desc',page_no=1,page_count=100)
    if payload is None:return False
    if not isinstance(payload,dict) or not isinstance(payload.get('list'),list):raise StorageError('DART 공시목록 응답 형식 미확인')
    try:pages=int(payload['total_page']);count=int(payload['total_count'])
    except (KeyError,ValueError,TypeError):raise StorageError('DART 공시목록 페이지 정보 미확인') from None
    rows=payload['list']
    if pages not in (0,1) or count!=len(rows):raise StorageError('DART 공시목록 전체 페이지 확인 필요')
    changed=False
    for row in rows:
        if not isinstance(row,dict) or row.get('corp_code')!=corp or row.get('stock_code')!=code:
            raise StorageError('DART 공시목록 기업 식별 불일치')
        receipt=str(row.get('rcept_no',''));day=str(row.get('rcept_dt',''));name=row.get('report_nm')
        if not re.fullmatch(r'\d{14}',receipt) or not re.fullmatch(r'\d{8}',day) or not isinstance(name,str):
            raise StorageError('DART 공시 접수번호·날짜·보고서명 미확인')
        if any(n in name for n in ('사업보고서','반기보고서','분기보고서')) and day>=original.strftime('%Y%m%d') and receipt not in known:
            changed=True
    return changed


def check_kis(client,saved,today):
    probe=run_probe(client,saved['data']['code'])
    ratios=next((r for r in probe.get('results',[]) if r.get('path')==RATIOS),{})
    if not ratios.get('success') or ratios.get('more_pages'):raise StorageError('KIS 연간 EPS 응답·전체 페이지 확인 필요')
    candidate=build_reference(probe,today,saved['data'].get('name'))
    candidate['quote']=saved.get('quote',{})  # EPS comparison never advances the price timestamp.
    candidate=clean_snapshot(candidate)
    def values(item):
        return sorted((r['period_end'],r['value']) for r in item['data']['rows'] if r.get('metric') in ('기본 EPS','KIS EPS') and r.get('report_code')=='11011')
    return values(candidate)!=values(saved),candidate
