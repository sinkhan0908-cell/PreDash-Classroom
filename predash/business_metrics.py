"""Consolidated revenue/operating profit from explicit DART XBRL totals.

Raw KRW facts stay separate from display values in 100 million KRW. Prior-year
comparatives and standalone quarter facts must come from the same filing.
"""
import calendar
import hashlib
import math
import re
from datetime import date,datetime
from decimal import Decimal,InvalidOperation
from zoneinfo import ZoneInfo
from predash.dart_xbrl import instances,X,D,local
from predash.company_codes import KNOWN_COMPANIES

VERSION=1
REASONS={
    'BIZ_IDENTITY':'매출·영업이익 원문의 회사 식별자가 일치하지 않습니다.',
    'BIZ_PERIOD':'매출·영업이익 보고기간·접수일을 확인할 수 없습니다.',
    'BIZ_MISSING':'연결 전체 매출·영업이익의 계정·기간·KRW 단위를 확인할 수 없습니다.',
    'BIZ_CONFLICT':'같은 연결 전체 계정·기간의 금액이 서로 다릅니다.',
    'BIZ_SCHEMA':'저장된 매출·영업이익의 형식 또는 원문 연결을 확인할 수 없습니다.',
}
class BusinessError(ValueError):pass


def stamp():return datetime.now(ZoneInfo('Asia/Seoul')).isoformat(timespec='seconds')


def parse(body,code,corp_code,year,quarter,receipt,today,fetched_at=None):
    if not re.fullmatch(r'\d{6}',code) or not re.fullmatch(r'\d{8}',corp_code):raise BusinessError('BIZ_IDENTITY')
    if KNOWN_COMPANIES.get(code,{}).get('corp_code',corp_code)!=corp_code:raise BusinessError('BIZ_IDENTITY')
    try:
        if quarter not in (1,2,3,4) or not re.fullmatch(r'\d{14}',receipt):raise ValueError
        month=quarter*3;end=f'{year}-{month:02d}-{calendar.monthrange(year,month)[1]}'
        published=date(int(receipt[:4]),int(receipt[4:6]),int(receipt[6:8]))
        if not date.fromisoformat(end)<published<=today:raise ValueError
    except (ValueError,TypeError,IndexError):raise BusinessError('BIZ_PERIOD') from None
    cumulative=[(f'{year}-01-01',end),(f'{year-1}-01-01',str(year-1)+end[4:])]
    standalone=[(f'{y}-{month-2:02d}-01',f'{y}'+end[4:]) for y in (year,year-1)]
    periods=list(dict.fromkeys(cumulative+standalone))
    facts={p:{'revenue':[],'operating_profit':[]} for p in periods}
    for root in instances(body):
        contexts={}
        for context in root.findall('{'+X+'}context'):
            p=(context.findtext('{'+X+'}period/{'+X+'}startDate'),context.findtext('{'+X+'}period/{'+X+'}endDate'))
            if p not in facts:continue
            pairs=[(local(m.get('dimension','')),local(m.text or '')) for m in context.findall('.//{'+D+'}explicitMember')]
            if pairs!=[('ConsolidatedAndSeparateFinancialStatementsAxis','ConsolidatedMember')]:continue
            if context.findall('.//{'+D+'}typedMember'):continue
            ident=context.find('{'+X+'}entity/{'+X+'}identifier')
            if ident is None or (ident.text or '').strip()!=corp_code or ident.get('scheme')!='http://dart.fss.or.kr/ifrs/CIK':raise BusinessError('BIZ_IDENTITY')
            if context.get('id') in contexts:raise BusinessError('BIZ_CONFLICT')
            contexts[context.get('id')]=p
        units={}
        for unit in root.findall('{'+X+'}unit'):
            measures=unit.findall('{'+X+'}measure')
            valid=len(measures)==1 and local(measures[0].text or '')=='KRW' and unit.find('{'+X+'}divide') is None
            if unit.get('id') in units and units[unit.get('id')]!=valid:raise BusinessError('BIZ_CONFLICT')
            units[unit.get('id')]=valid
        for fact in root:
            p=contexts.get(fact.get('contextRef'))
            if not p or not units.get(fact.get('unitRef')) or fact.get('scale') is not None:continue
            key=None
            if re.fullmatch(r'\{https?://xbrl\.ifrs\.org/taxonomy/\d{4}-\d{2}-\d{2}/ifrs-full\}Revenue',fact.tag):key='revenue'
            elif re.fullmatch(r'\{https?://dart\.fss\.or\.kr/taxonomy/\d{4}-\d{2}-\d{2}/ifrs/dart\}OperatingIncomeLoss',fact.tag):key='operating_profit'
            if not key:continue
            try:
                value=Decimal((fact.text or '').strip())
                if not value.is_finite():raise ValueError
                value=int(value) if value==value.to_integral_value() else float(value)
            except (InvalidOperation,ValueError,OverflowError):continue
            facts[p][key].append((value,fact.tag,fact.get('contextRef')))
    rows=[]
    for p,values in facts.items():
        if any(len({v[0] for v in group})>1 for group in values.values()):raise BusinessError('BIZ_CONFLICT')
        if any(not group for group in values.values()):
            if p in cumulative:raise BusinessError('BIZ_MISSING')
            continue
        row={'period_start':p[0],'period_end':p[1],'basis':'CFS','currency':'KRW','context_scope':'explicit_consolidated_total',
             'revenue':values['revenue'][0][0],'operating_profit':values['operating_profit'][0][0],
             'concepts':{key:group[0][1] for key,group in values.items()},'contexts':{key:group[0][2] for key,group in values.items()}}
        rows.append(row)
    return {'version':VERSION,'status':'success','code':code,'corp_code':corp_code,'year':year,'quarter':quarter,
            'basis':'CFS','currency':'KRW','report_code':{1:'11013',2:'11012',3:'11014',4:'11011'}[quarter],
            'receipt':receipt,'source':'https://dart.fss.or.kr/dsaf001/main.do?rcpNo='+receipt,
            'document_sha256':hashlib.sha256(body).hexdigest(),'period_start':cumulative[0][0],'period_end':end,
            'available_on':published.isoformat(),'fetched_at':fetched_at or stamp(),'parsed_at':stamp(),'rows':rows,
            'source_location':'XBRL 연결 전체 매출·영업이익 · 당기 및 전년 동기 · 누적/단독 기간 분리'}


def validate(block,code):
    """Validate stored facts before deriving any display values."""
    try:
        if not isinstance(block,dict) or block.get('version')!=VERSION or block.get('status')!='success' or block.get('code')!=code:raise ValueError
        if block['basis']!='CFS' or block['currency']!='KRW' or not re.fullmatch(r'\d{8}',block['corp_code']):raise ValueError
        if KNOWN_COMPANIES.get(code,{}).get('corp_code',block['corp_code'])!=block['corp_code']:raise ValueError
        year,quarter=block['year'],block['quarter']
        if type(year) is not int or type(quarter) is not int or quarter not in (1,2,3,4):raise ValueError
        month=quarter*3;end=f'{year}-{month:02d}-{calendar.monthrange(year,month)[1]}'
        if block['period_start']!=f'{year}-01-01' or block['period_end']!=end:raise ValueError
        if block['report_code']!={1:'11013',2:'11012',3:'11014',4:'11011'}[quarter]:raise ValueError
        receipt=block['receipt']
        if not re.fullmatch(r'\d{14}',receipt) or block['source']!='https://dart.fss.or.kr/dsaf001/main.do?rcpNo='+receipt:raise ValueError
        if not re.fullmatch(r'[a-f0-9]{64}',block['document_sha256']):raise ValueError
        published=date(int(receipt[:4]),int(receipt[4:6]),int(receipt[6:8]))
        if block['available_on']!=published.isoformat() or not date.fromisoformat(end)<published:raise ValueError
        if datetime.fromisoformat(block['fetched_at']).tzinfo is None:raise ValueError
        expected={(f'{y}-01-01',str(y)+end[4:]) for y in (year,year-1)}
        expected|={(f'{y}-{month-2:02d}-01',str(y)+end[4:]) for y in (year,year-1)}
        periods=[]
        for row in block['rows']:
            p=(row['period_start'],row['period_end']);periods.append(p)
            if p not in expected or row['basis']!='CFS' or row['currency']!='KRW' or row['context_scope']!='explicit_consolidated_total':raise ValueError
            for key in ('revenue','operating_profit'):
                if type(row[key]) not in (int,float) or not math.isfinite(row[key]):raise ValueError
                pattern=(r'\{https?://xbrl\.ifrs\.org/taxonomy/\d{4}-\d{2}-\d{2}/ifrs-full\}Revenue' if key=='revenue' else r'\{https?://dart\.fss\.or\.kr/taxonomy/\d{4}-\d{2}-\d{2}/ifrs/dart\}OperatingIncomeLoss')
                if not re.fullmatch(pattern,row['concepts'][key]) or not row['contexts'][key]:raise ValueError
        if len(periods)!=len(set(periods)):raise ValueError
        if not {(f'{y}-01-01',str(y)+end[4:]) for y in (year,year-1)}<=set(periods):raise ValueError
        return block
    except (KeyError,ValueError,TypeError,OverflowError):raise BusinessError('BIZ_SCHEMA') from None


def view(ttm,code,today=None):
    """Legacy-compatible quarterly metrics; unknown/old snapshots return None."""
    try:
        if not isinstance(ttm,dict) or ttm.get('code')!=code or ttm.get('status')!='success':return None
        block=validate(ttm.get('business_metrics'),code)
        anchor=max(ttm['inputs'],key=lambda r:r['period_end'])
        if any(block[k]!=anchor[k] for k in ('receipt','document_sha256','period_end')):return None
        if today and date.fromisoformat(block['available_on'])>today:return None
        rows={(r['period_start'],r['period_end']):r for r in block['rows']}
        year,quarter=block['year'],block['quarter'];end=block['period_end']
        current=rows[(f'{year}-01-01',end)];prior=rows[(f'{year-1}-01-01',str(year-1)+end[4:])]
        def metrics(a,b):
            values={name:a[key]/1e8 if a else None for name,key in (('revenue','revenue'),('profit','operating_profit'))}
            values.update({name:b[key]/1e8 if b else None for name,key in (('prior_revenue','revenue'),('prior_profit','operating_profit'))})
            for field,base,out in (('revenue','prior_revenue','revenue_growth_pct'),('profit','prior_profit','growth_pct')):
                values[out]=(values[field]/values[base]-1)*100 if values[field] is not None and values[base] is not None and values[base]>0 else None
            values['margin_pct']=values['profit']/values['revenue']*100 if values['profit'] is not None and values['revenue'] is not None and values['revenue']>0 else None
            return values
        result=metrics(current,prior)
        month=quarter*3
        a=rows.get((f'{year}-{month-2:02d}-01',end));b=rows.get((f'{year-1}-{month-2:02d}-01',str(year-1)+end[4:]))
        result.update(standalone=metrics(a,b),standalone_available=bool(a and b),year=year,quarter=quarter,
                      basis='CFS',receipt=block['receipt'],source=block['source'],fetched=block['fetched_at'],
                      document_sha256=block['document_sha256'],period_start=block['period_start'],period_end=end,
                      currency='KRW',display_unit='억원',source_route='DART XBRL · PC 검증 저장본')
        return result
    except (BusinessError,KeyError,TypeError,ValueError):return None
