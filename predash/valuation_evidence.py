"""Label annual valuation inputs and compare dated public EPS references.

Reference facts never replace provider inputs or imply live/full filing verification.
"""
import json
import math
from copy import deepcopy
from datetime import date
from pathlib import Path

REFERENCE_PATH=Path(__file__).parent/'data'/'eps_reference_checks.json'


def references():
    try:
        data=json.loads(REFERENCE_PATH.read_text(encoding='utf-8'))
        return data['references'] if data.get('schema_version')==1 and isinstance(data.get('references'),list) else []
    except (OSError,ValueError,KeyError,TypeError):return []


def finite(value):return type(value) in (int,float) and math.isfinite(value)


def describe(saved,result,today,reference_rows=None):
    """Return derived evidence, without changing cached facts or raw calculations."""
    result=deepcopy(result)
    data=saved['data'];source=saved.get('source','DART')
    annual=sorted([r for r in data.get('rows',[]) if r.get('metric') in ('기본 EPS','KIS EPS') and r.get('report_code')=='11011' and r.get('period_type')=='연간'],key=lambda r:r['year'])
    latest=annual[-1] if annual else {}
    refs=references() if reference_rows is None else reference_rows
    comparisons=[]
    for row in annual:
        matches=[r for r in refs if r.get('code')==data.get('code') and r.get('year')==row.get('year') and
                 r.get('period_end')==row.get('period_end') and r.get('report_code')=='11011' and r.get('unit')=='원/주']
        # Conflicting or malformed reference rows cannot validate a provider input.
        if len(matches)!=1 or row.get('unit')!='원/주':continue
        ref=matches[0]
        if ref.get('metric')!='보통주 기본 EPS' or ref.get('accounting_standard')!='K-IFRS' or ref.get('basis') not in ('CFS','OFS'):continue
        try:
            if date.fromisoformat(ref['checked_on'])>date.fromisoformat(str(today)):continue
        except (KeyError,ValueError,TypeError):continue
        if not finite(ref.get('value')) or not finite(row.get('value')) or not str(ref.get('source','')).startswith('https://'):continue
        if source=='DART' and (row.get('basis',data.get('basis'))!=ref.get('basis') or row.get('metric')!='기본 EPS'):continue
        equal=abs(row['value']-ref['value'])<=max(.01,abs(ref['value'])*1e-6)
        comparisons.append({
            'year':row['year'],'period_end':row['period_end'],'provider':source,'provider_eps':row['value'],
            'reference_eps':ref['value'],'difference':row['value']-ref['value'],
            'status':'numeric_match' if equal else 'numeric_mismatch',
            'definition_match':None if source=='KIS' else True,
            'reference_basis':ref['basis'],'reference_metric':ref['metric'],'reference_unit':ref['unit'],
            'checked_on':ref['checked_on'],'source':ref['source'],'source_location':ref.get('source_location'),
        })
    mismatch=any(r['status']=='numeric_mismatch' for r in comparisons)
    year=latest.get('year');year_label=str(year) if year is not None else '연도 미확인'
    result['valuation_basis']={
        'per_type':'annual_eps','per_label':year_label+'년 연간 EPS 기준 PER','eps_year':year,
        'eps_value':latest.get('value'),'eps_period_end':latest.get('period_end'),'eps_unit':'원/주',
        'eps_definition':'KIS EPS · 기본/희석·연결/별도 미확인' if source=='KIS' else '기본 EPS · '+str(data.get('basis')),
        'price_date':saved.get('quote',{}).get('date'),'price':saved.get('quote',{}).get('close'),
        'per_formula':'표시 가격 ÷ 마지막 완료 사업연도 EPS',
        'peg_label':'연간 PER 기준 과거 PEG','peg_formula':'연간 EPS 기준 PER ÷ 4년 EPS CAGR(%)',
        'growth_start_year':annual[0]['year'] if annual else None,'growth_end_year':year,
        'growth_percent':result.get('cagr'),'ttm_per':None,
        'ttm_gap':'최근 12개월 이익·EPS의 기간·회계범위·주식수 기준을 검증하지 않아 미산출',
        'interpretation':'최근 12개월(TTM) PER 또는 예상 PER이 아님',
    }
    result['eps_crosscheck']={'status':'numeric_mismatch' if mismatch else 'partial_numeric_match' if comparisons else 'not_checked',
        'compared_years':len(comparisons),'input_years':len(annual),'comparisons':comparisons,
        'definition_status':'unverified' if source=='KIS' else 'dart_api_basic_eps',
        'scope':'확인일이 기록된 원문의 일부 EPS 수치 대조. 조회 성공·변경 없음·전체 검증 완료와 구분하며 이후 정정 가능성은 별도 확인 필요.'}
    result['verification']={'provider_response':'API 입력자료 사용',
        'filing_crosscheck':'공시와 EPS 수치 불일치 · 정의 차이 가능' if mismatch else '일부 EPS 수치 일치 · 전체 검증 미완료' if comparisons else '공시 EPS 별도 대조 미실시',
        'valuation_status':'reference_only_mismatch' if mismatch else 'reference_only' if source=='KIS' else 'calculated_from_dart_inputs',
        'price_crosscheck':'시세 제공처 응답 사용 · 별도 원문 대조 미실시'}
    gaps=list(result.get('data_gaps',[]))
    gaps.append(result['valuation_basis']['ttm_gap'])
    if source=='KIS':gaps.append('KIS EPS의 연결·별도·기본·희석 정의 미대조')
    if mismatch:gaps.append('API EPS와 확인일 기준 공시 기본 EPS 수치 불일치: 원인 미확인, PER·PEG·성장률은 참고 계산')
    result['data_gaps']=list(dict.fromkeys(gaps))
    return result
