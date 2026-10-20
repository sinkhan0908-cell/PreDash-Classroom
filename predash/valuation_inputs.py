"""Select dated official annual inputs without mutating provider snapshots."""
from copy import deepcopy
from datetime import date
from predash.ttm import calculate, VERSION
from predash.lynch import analyse


INPUTS_VERSION=2

def official_annual(saved, today):
    block=saved.get('ttm') or {}
    if block.get('code')!=saved['data']['code'] or (block.get('status')!='success' and block.get('annual_eps_status')!='success'):return {}
    candidates=list(block.get('annual_eps',[]))+list(block.get('inputs',[])[:1])
    accepted={}
    for row in candidates:
        if not isinstance(row,dict):continue
        try:
            year=date.fromisoformat(row['period_end']).year
            if row['period_start']!=f'{year}-01-01' or row['period_end']!=f'{year}-12-31':continue
            check=calculate({'version':VERSION,'status':'success','inputs':[row]},
                            {'close':1,'date':str(today),'source':'validation'},date.fromisoformat(str(today)))
            if check['eps'] is None or any(not g.startswith(('공시의 반올림','IR 보고서 작성일','최근 12개월 보통주 이익')) for g in check['data_gaps']):continue
            accepted.setdefault(year,deepcopy(row))
        except (KeyError,ValueError,TypeError):continue
    return accepted


def apply_annual(saved, result, today):
    """Use official definitions for calculations; preserve raw API values in evidence."""
    official=official_annual(saved,today)
    if not official:return result, {'status':'provider_unverified','years':[]}
    data=deepcopy(saved['data']);rows=[]
    is_kis=saved.get('source')=='KIS'
    for row in data.get('rows',[]):
        if row.get('metric') not in ('기본 EPS','KIS EPS') or row.get('report_code')!='11011' or row.get('period_type')!='연간':
            rows.append(row);continue
        row['provider_value']=row.get('value');row['provider_source']=row.get('source')
        ref=official.get(row.get('year'))
        # Never combine unverified KIS definitions with official EPS into a growth rate.
        if ref and row.get('period_end')==ref['period_end']:
            row.update(metric='기본 EPS',value=ref['reported_eps'],basis='CFS',unit='원/주',
                       source=ref['source'],source_location=ref.get('source_location'),
                       document_sha256=ref.get('document_sha256'),available_on=ref['available_on'],
                       applied_definition='연결 보통주 기본 EPS',fetched_at=ref.get('fetched_at',saved['ttm'].get('fetched_at')))
        elif is_kis:
            row.update(metric='기본 EPS',value=None,data_gap='동일 기준의 공식 연간 EPS 미확인')
        elif row.get('basis',data.get('basis'))!='CFS':
            row.update(value=None,data_gap='연결 EPS와 별도 EPS 혼합 방지')
        rows.append(row)
    data['rows']=rows
    data.setdefault('lynch',{}).setdefault('eps_comparability_gaps',[]).extend(saved['ttm'].get('annual_comparability_gaps',[]))
    recalculated=analyse(data,saved.get('quote',{}),str(today))
    if is_kis and any(r.get('value') is None for r in recalculated['history']):
        recalculated['growth_gaps'].append('공식 연결 보통주 기본 EPS 5개 연도 확인 필요 · KIS 값과 혼합하지 않음')
    merged={**result,**recalculated}
    return merged, {'status':'official_applied','years':sorted(official),
                    'source_fetched_at':saved['ttm'].get('annual_source_fetched_at',saved['ttm'].get('fetched_at')),
                    'scope':'공식 연결 보통주 기본 EPS 우선 · API 원자료 보존 · 미확인 연도는 성장률 계산 제외'}
