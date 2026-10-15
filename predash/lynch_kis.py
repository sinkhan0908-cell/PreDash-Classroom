"""KIS-only reference calculations. Never claim DART accounting verification."""
import re
import time
from datetime import date
from predash.kis import BrokerError
from predash.kis_probe import run_probe,numeric,RATIOS,PRICE
from predash.lynch import analyse


def build_reference(probe, today, name=None):
    if probe.get('authentication_error'):raise BrokerError(probe['authentication_error'])
    price=next((r for r in probe['results'] if r['path']==PRICE),{})
    ratios=next((r for r in probe['results'] if r['path']==RATIOS),{})
    if not price.get('success') and not ratios.get('success'):
        raise BrokerError('KIS 현재가·연간 EPS 모두 조회 실패: '+str(ratios.get('message_code') or price.get('message_code') or '연결 확인 필요'))
    fields=price.get('values',{})
    month=fields.get('stac_month')
    gaps=[]
    if month is None or month!=int(month) or not 1<=month<=12:
        month=None;gaps.append('KIS 결산월 미확인: 연간·중간기간 구분을 확정할 수 없어 CAGR 보류')
    else:month=int(month)
    annual=[];excluded=[]
    for item in ratios.get('annual_eps',[]):
        period=item['period']
        if month and int(period[4:])==month and period<today.strftime('%Y%m'):
            annual.append(item)
        else:excluded.append(period)
    annual=sorted(annual,key=lambda r:r['period'])[-5:]
    if ratios.get('more_pages'):gaps.append('KIS 추가 페이지 미검증: 최근 5개 결산연도 확인 필요')
    data={'code':probe['code'],'name':name or probe['code'],'basis':'KIS 회계 기준 미확인','fetched_at':probe['fetched_at'],
          'asof':today.isoformat(),'rows':[], 'lynch':{'eps_comparability_gaps':gaps},'data_gaps':[
          '연결·별도 및 기본·희석 EPS 정의 미대조','주식 분할·재작성 반영 여부 미대조','현금·차입금은 이 경로에서 미수집']}
    for item in annual:
        year=int(item['period'][:4]);month=int(item['period'][4:])
        import calendar
        data['rows'].append({'metric':'KIS EPS','value':item['eps'],'year':year,'report_code':'11011','period_type':'연간',
            'period_end':date(year,month,calendar.monthrange(year,month)[1]).isoformat(),'source':'https://apiportal.koreainvestment.com/',
            'receipt':None,'unit':'원/주','basis':data['basis'],'data_gap':None,'fetched_at':probe['fetched_at']})
    # Preserve the provider label; EPS subtype has not been verified.
    for row in data['rows']:row['provider_metric']='KIS EPS · 기본/희석 미확인'
    quote={'close':fields.get('stck_prpr'),'date':probe['fetched_at'][:10],'source':'KIS 모의 현재가',
           'fetched_at':probe['fetched_at'],'kind':'현재가'} if price.get('success') else {'error':price.get('reason','현재가 미확인')}
    return {'data':data,'quote':quote,'source':'KIS','probe':probe,'excluded_periods':excluded,
            'validation_level':'provider_reference_only'}


def collect_reference(client,code,today,name=None,pause=time.sleep):
    probe=run_probe(client,code,pause=pause)
    saved=build_reference(probe,today,name)
    try:
        pause(1.1)
        rows=client.price_history(code,today)
        # Strictly prior trading days: never label the current incomplete day as a close.
        eligible=[]
        for row in rows:
            day=str(row.get('basDt',''))
            value=numeric(row.get('clpr'))
            try: parsed=date.fromisoformat(f'{day[:4]}-{day[4:6]}-{day[6:]}') if re.fullmatch(r'\d{8}',day) else None
            except ValueError:parsed=None
            if parsed and parsed<today and value is not None and value>0:
                eligible.append((day,value,parsed.isoformat()))
        if not eligible:raise BrokerError('이전 거래일 종가 미확인')
        _,close,day=max(eligible)
        saved['quote']={'close':close,'date':day,'source':'KIS 모의 일별 시세','fetched_at':probe['fetched_at'],'kind':'종가'}
    except BrokerError as exc:
        saved['quote']['closing_gap']=str(exc)
    return saved


def calculate_reference(saved,today):
    data={**saved['data'],'rows':[{**r,'metric':'기본 EPS'} for r in saved['data']['rows']]}
    result=analyse(data,saved['quote'],today.isoformat())
    for row in result['history']:row['metric']='KIS EPS'
    result['validation_level']='provider_reference_only'
    return result
