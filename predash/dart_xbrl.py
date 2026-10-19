"""Strict ordinary-basic EPS from dated DART XBRL contexts, without company.json.

A fresh official IR identity proof and live filing-list identity are both required.
Only exact IFRS concepts, consolidated contexts and matching units are supported.
"""
import hashlib
import io
import math
import re
import zipfile
from datetime import date,timedelta
from decimal import Decimal,InvalidOperation
from xml.etree import ElementTree as ET
from predash.ttm import TtmError,VERSION,now,calculate
from predash.company_codes import company_name_key

X='http://www.xbrl.org/2003/instance'
D='http://xbrl.org/2006/xbrldi'
CONCEPTS={'profit':'ProfitLossAttributableToOrdinaryEquityHoldersOfParentEntity',
          'weighted_shares':'WeightedAverageNumberOfOrdinarySharesOutstanding',
          'reported_eps':'BasicEarningsLossPerShare'}
REPORTS={3:'11013',6:'11012',9:'11014',12:'11011'}


def local(value):return value.rsplit('}',1)[-1].split(':')[-1]


def instances(body):
    if len(body)>16000000:raise TtmError('DART XBRL 압축 크기 한도 초과')
    try:
        archive=zipfile.ZipFile(io.BytesIO(body));items=archive.infolist()
        if len(items)>300 or sum(i.file_size for i in items)>64000000:raise TtmError('DART XBRL 압축 해제 한도 초과')
        roots=[]
        for item in items:
            if item.is_dir() or not item.filename.lower().endswith(('.xbrl','.xml')):continue
            raw=archive.read(item)
            if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise TtmError('XBRL 외부 선언 미지원')
            root=ET.fromstring(raw)
            if root.tag=='{'+X+'}xbrl':roots.append(root)
        if not roots:raise TtmError('DART XBRL 인스턴스 미확인')
        return roots
    except (zipfile.BadZipFile,ET.ParseError,RuntimeError,ValueError):raise TtmError('DART XBRL ZIP·XML 형식 확인 필요') from None


def parse(body,periods,receipt,today):
    available=date.fromisoformat(f'{receipt[:4]}-{receipt[4:6]}-{receipt[6:8]}')
    if available>today:raise TtmError('기준일 이후 XBRL 접수번호')
    entities=set()
    facts={period:{key:[] for key in CONCEPTS} for period in periods}
    for root in instances(body):
        contexts={}
        for context in root.findall('{'+X+'}context'):
            ident=context.find('{'+X+'}entity/{'+X+'}identifier')
            start=context.findtext('{'+X+'}period/{'+X+'}startDate')
            end=context.findtext('{'+X+'}period/{'+X+'}endDate')
            period=(start,end)
            if period not in facts or ident is None or not ident.text:continue
            members=context.findall('.//{'+D+'}explicitMember')
            pairs=[(local(m.get('dimension','')),local(m.text or '')) for m in members]
            # No default-context inference, segment totals, diluted or preference members.
            allowed={('ConsolidatedAndSeparateFinancialStatementsAxis','ConsolidatedMember'),
                     ('ClassesOfShareCapitalAxis','OrdinarySharesMember')}
            if not pairs or any(p not in allowed for p in pairs) or not any(p[0]=='ConsolidatedAndSeparateFinancialStatementsAxis' for p in pairs):continue
            if context.findall('.//{'+D+'}typedMember'):continue
            entities.add((ident.get('scheme'),ident.text.strip()))
            if context.get('id') in contexts:raise TtmError('XBRL 기간 식별자 중복')
            contexts[context.get('id')]=period
        units={}
        for unit in root.findall('{'+X+'}unit'):
            measures=unit.findall('{'+X+'}measure')
            if len(measures)==1:kind=local(measures[0].text or '')
            else:
                num=unit.findtext('{'+X+'}divide/{'+X+'}unitNumerator/{'+X+'}measure')
                den=unit.findtext('{'+X+'}divide/{'+X+'}unitDenominator/{'+X+'}measure')
                kind=local(num or '')+'/'+local(den or '')
            units[unit.get('id')]=kind
        for fact in root:
            period=contexts.get(fact.get('contextRef'))
            # Extension concepts or similarly named company concepts are not inferred.
            if not period or not fact.tag.startswith('{http://xbrl.ifrs.org/taxonomy/'):continue
            for key,concept in CONCEPTS.items():
                if local(fact.tag)!=concept:continue
                expected={'profit':'KRW','weighted_shares':'shares','reported_eps':'KRW/shares'}[key]
                if units.get(fact.get('unitRef'))!=expected or fact.get('scale') is not None:continue
                try:value=float(Decimal((fact.text or '').strip()))
                except (InvalidOperation,ValueError):continue
                if math.isfinite(value):facts[period][key].append(value)
    if len(entities)>1:raise TtmError('XBRL 기업 식별자가 혼재합니다.')
    rows=[]
    for (start,end),values in facts.items():
        if any(not v or len(set(v))!=1 for v in values.values()):raise TtmError('XBRL 연결 보통주 기본 EPS 계정·기간·단위 누락 또는 불일치')
        if date.fromisoformat(end)>=available:raise TtmError('XBRL 보고기간·접수일 불일치')
        row={key:v[0] for key,v in values.items()}
        if row['weighted_shares']<=0 or abs(row['profit']/row['weighted_shares']-row['reported_eps'])>1.1:raise TtmError('XBRL 순이익·주식수·EPS 대조 불일치')
        row.update(period_start=start,period_end=end,basis='CFS',currency='KRW',definition='ordinary_basic',
            source='https://dart.fss.or.kr/dsaf001/main.do?rcpNo='+receipt,receipt=receipt,
            source_location='XBRL 연결·보통주 기본 EPS 기간별 표준 계정',document_sha256=hashlib.sha256(body).hexdigest(),
            available_on=available.isoformat(),available_on_type='filing_receipt_date',fetched_at=now())
        rows.append(row)
    return rows


def download(provider,receipt,report):
    from predash.official import get
    return get('https://opendart.fss.or.kr/api/fnlttXbrl.xml',
        {'crtfc_key':provider.dart_key,'rcept_no':receipt,'reprt_code':report}).content


def collect(provider,today,annual,read=download):
    if annual.get('code')!='214450' or annual.get('annual_eps_status')!='success' or not annual.get('annual_eps'):raise TtmError('독립적인 공식 IR 기업 식별 자료 필요')
    payload=provider.dart('list.json',corp_code='00970453',bgn_de=(today-timedelta(days=600)).strftime('%Y%m%d'),
        end_de=today.strftime('%Y%m%d'),pblntf_ty='A',last_reprt_at='Y',page_count='100') or {}
    if int(payload.get('total_page',1))>1:raise TtmError('DART 정기공시 목록 추가 페이지 미확인')
    reports={}
    for row in payload.get('list',[]):
        if row.get('corp_code')!='00970453' or company_name_key(row.get('corp_name'))!='파마리서치' or row.get('stock_code','214450')!='214450':raise TtmError('DART 공시 목록 기업 식별 불일치')
        m=re.fullmatch(r'(?:\[기재정정\])?(사업보고서|반기보고서|분기보고서)\s*\((20\d{2})\.(03|06|09|12)\)',row.get('report_nm',''))
        if not m:continue
        name,y,month=m[1],int(m[2]),int(m[3]);receipt=row.get('rcept_no','')
        if not re.fullmatch(r'\d{14}',receipt):raise TtmError('DART 접수번호 확인 필요')
        if (month==12 and name!='사업보고서') or (month==6 and name!='반기보고서') or (month in (3,9) and name!='분기보고서'):raise TtmError('DART 보고서명·대상 기간 불일치')
        end=date(y,month,{3:31,6:30,9:30,12:31}[month])
        if end>=today:continue
        reports[y,month]=max(receipt,reports.get((y,month),''))
    if not reports:raise TtmError('DART 최근 정기공시 목록 미확인')
    y,month=max(reports)
    if y<today.year-1:raise TtmError('DART 최근 완료 기간 미확인')
    if month==12:
        inputs=parse(read(provider,reports[y,month],REPORTS[month]),[(f'{y}-01-01',f'{y}-12-31')],reports[y,month],today)
    else:
        suffix=f'{month:02d}-{31 if month in (3,12) else 30}'
        current=parse(read(provider,reports[y,month],REPORTS[month]),[(f'{y}-01-01',f'{y}-{suffix}'),(f'{y-1}-01-01',f'{y-1}-{suffix}')],reports[y,month],today)
        if (y-1,12) not in reports:raise TtmError('DART 전년 연간 보고서 미확인')
        previous=reports[y-1,12]
        inputs=parse(read(provider,previous,'11011'),[(f'{y-1}-01-01',f'{y-1}-12-31')],previous,today)+current
    # A mismatch with the independently obtained IR annual note needs explicit review.
    for row in inputs:
        comparable=[r for r in annual['annual_eps'] if r['period_start']==row['period_start'] and r['period_end']==row['period_end']]
        if comparable and any(abs(r['reported_eps']-row['reported_eps'])>1.1 for r in comparable):raise TtmError('DART XBRL과 공식 IR 연간 EPS 불일치 · 정정 여부 확인 필요')
    block={**annual,'status':'success','inputs':inputs,'reason':None,'source_route':'DART XBRL CFS ordinary EPS + official IR annual EPS',
        'last_attempt_at':now(),'fetched_at':now(),'latest_scope':'기업명이 일치하는 DART 정기공시 목록의 최신 완료 기간 · 원문 XBRL 계정·기간·단위 대조'}
    checked=calculate(block,{'close':1,'date':today.isoformat(),'source':'validation'},today)
    if checked['eps'] is None:raise TtmError('XBRL TTM 기간·순이익·주식수 대조 실패')
    return block
