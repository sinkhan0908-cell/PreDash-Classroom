"""Public financial evidence only; API consistency checks are not an audit."""
import calendar
import math
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from predash.official import DataError

# section, standard ID, conservative exact-name fallbacks, display unit
ACCOUNTS = {
    '매출': ('IS', 'ifrs-full_Revenue', ('매출액', '수익(매출액)'), '원'),
    '영업이익': ('IS', 'dart_OperatingIncomeLoss', ('영업이익', '영업이익(손실)'), '원'),
    '지배주주순이익': ('IS', 'ifrs-full_ProfitLossAttributableToOwnersOfParent', ('지배기업의 소유주에게 귀속되는 당기순이익(손실)',), '원'),
    '기본 EPS': ('IS', 'ifrs-full_BasicEarningsLossPerShare', ('기본주당이익', '기본주당이익(손실)', '기본주당순이익'), '원/주'),
    '자산총계': ('BS', 'ifrs-full_Assets', ('자산총계',), '원'),
    '부채총계': ('BS', 'ifrs-full_Liabilities', ('부채총계',), '원'),
    '자본총계': ('BS', 'ifrs-full_Equity', ('자본총계',), '원'),
    '지배주주자본': ('BS', 'ifrs-full_EquityAttributableToOwnersOfParent', ('지배기업의 소유주에게 귀속되는 자본',), '원'),
    '영업현금흐름': ('CF', 'ifrs-full_CashFlowsFromUsedInOperatingActivities', ('영업활동현금흐름', '영업활동으로 인한 현금흐름'), '원'),
    '유형자산 취득': ('CF', 'ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities', ('유형자산의 취득',), '원'),
    '무형자산 취득': ('CF', 'ifrs-full_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities', ('무형자산의 취득',), '원'),
}
QUARTERS = {'11011': 4, '11014': 3, '11012': 2, '11013': 1}


def numeric(raw):
    text = str(raw).strip().replace(',', '')
    if text.startswith('(') and text.endswith(')'):
        text = '-' + text[1:-1]
    try:
        value = float(text)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def parse_statement(rows, year, report_code, basis, fetched, december_year_end=True):
    quarter = QUARTERS[report_code]
    month = quarter * 3
    end = date(year, month, calendar.monthrange(year, month)[1]).isoformat() if december_year_end else None
    receipts = {r.get('rcept_no') for r in rows if r.get('rcept_no')}
    receipt = next(iter(receipts)) if len(receipts) == 1 else None
    source = 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=' + receipt if receipt else None
    common_gap = None
    if not receipt or not re.fullmatch(r'\d{14}', receipt):
        common_gap = '공시 접수번호 누락 또는 혼재'
    elif receipt[:8] > fetched[:10].replace('-', ''):
        common_gap = '조회 기준일 이후 공시'
    elif not december_year_end:
        common_gap = '12월 결산 여부 미확인: 정확한 회계기간 확인 필요'
    elif end > fetched[:10]:
        common_gap = '아직 종료되지 않은 보고기간'
    elif any((r.get('bsns_year') and str(r['bsns_year']) != str(year)) or
             (r.get('reprt_code') and r['reprt_code'] != report_code) for r in rows):
        common_gap = '응답의 사업연도 또는 보고서 코드 불일치'
    output = []
    for label, (section, account_id, names, unit) in ACCOUNTS.items():
        candidates = [r for r in rows if r.get('sj_div') in (('IS', 'CIS') if section == 'IS' else (section,))
                      and (r.get('account_id') == account_id or r.get('account_nm') in names)]
        field = 'thstrm_add_amount' if section == 'IS' and quarter in (2, 3) else 'thstrm_amount'
        values = [numeric(r.get(field)) for r in candidates]
        value, reason = None, common_gap
        if not reason:
            if not candidates:
                reason = '계정 누락 또는 계정명 미지원'
            elif any(str(r.get('currency', '')).upper() != 'KRW' for r in candidates):
                reason = 'KRW 통화 확인 실패'
            elif any(v is None for v in values):
                reason = '금액 누락 또는 비정상 숫자'
            elif len(set(values)) != 1:
                reason = '동일 계정의 값이 서로 다름: 원문 대조 필요'
            elif basis == 'OFS' and label.startswith('지배주주'):
                reason = '별도 재무제표: 지배주주 기준 계정 미적용'
            else:
                value = values[0]
        output.append({'metric': label, 'value': value, 'unit': unit, 'currency': 'KRW' if value is not None else None,
                       'year': year, 'report_code': report_code, 'basis': basis,
                       'period_start': None if section == 'BS' or not end else f'{year}-01-01',
                       'period_end': end, 'period_type': '기말' if section == 'BS' else '연간' if quarter == 4 else '누적',
                       'source': source, 'receipt': receipt, 'fetched_at': fetched,
                       'account_ids': sorted({r.get('account_id', '') for r in candidates}),
                       'raw_values': [r.get(field) for r in candidates], 'amount_field': field,
                       'status': 'API 형식 확인 · 원문 대조 필요' if value is not None else '보류',
                       'data_gap': reason})
    by_name = {r['metric']: r for r in output}
    balance = [by_name[k]['value'] for k in ('자산총계', '부채총계', '자본총계')]
    if all(v is not None for v in balance) and abs(balance[0] - balance[1] - balance[2]) > max(1, abs(balance[0]) * 1e-9):
        for name in ('자산총계', '부채총계', '자본총계', '지배주주자본'):
            by_name[name].update(value=None, status='보류', data_gap='자산 = 부채 + 자본 불일치: 원문 대조 필요')
    return output


def collect(provider, code, asof=None):
    """Fresh request per click, fixed accounting basis, no prices/credentials in output."""
    asof = asof or datetime.now(ZoneInfo('Asia/Seoul')).date()
    if not re.fullmatch(r'[0-9]{6}', code):
        raise DataError('종목코드는 숫자 6자리여야 합니다.')
    fetched = datetime.now(ZoneInfo('Asia/Seoul')).isoformat(timespec='seconds')
    corp = provider.corp(code)
    company = provider.dart('company.json', corp_code=corp) or {}
    december = str(company.get('acc_mt', '')).zfill(2) == '12'
    cache = {}
    def fetch(year, report, basis):
        key = (year, report, basis)
        if key not in cache:
            data = provider.dart('fnlttSinglAcntAll.json', corp_code=corp, bsns_year=str(year), reprt_code=report, fs_div=basis)
            cache[key] = (data or {}).get('list') or []
        return cache[key]
    # Include prior annual reports in the chronology, not just interim reports.
    latest = None
    for year in (asof.year, asof.year - 1):
        for report in ('11011', '11014', '11012', '11013'):
            month = QUARTERS[report] * 3
            if date(year, month, calendar.monthrange(year, month)[1]) >= asof:
                continue
            for basis in ('CFS', 'OFS'):
                rows = fetch(year, report, basis)
                if rows:
                    latest = (year, report, basis, rows)
                    break
            if latest:
                break
        if latest:
            break
    if not latest:
        raise DataError('최근 2개 사업연도의 공시 재무제표가 없습니다.')
    year, report, basis, rows = latest
    last_annual = year if report == '11011' else year - 1
    evidence = parse_statement(rows, year, report, basis, asof.isoformat(), december)
    for annual_year in range(last_annual, last_annual - 5, -1):
        if annual_year == year and report == '11011':
            continue
        evidence.extend(parse_statement(fetch(annual_year, '11011', basis), annual_year, '11011', basis, asof.isoformat(), december))
    for row in evidence:
        row['fetched_at'] = fetched
    opening_equity = []
    for annual_year in range(last_annual, last_annual - 5, -1):
        # Same filing's comparative balance captures restatements and avoids mixing vintages.
        annual_rows = fetch(annual_year, '11011', basis)
        comparative = [{**r, 'thstrm_amount': r.get('frmtrm_amount')} for r in annual_rows]
        parsed = parse_statement(comparative, annual_year, '11011', basis, asof.isoformat(), december)
        opening = next(r for r in parsed if r['metric'] == '지배주주자본')
        opening.update(metric='기초 지배주주자본', amount_field='frmtrm_amount', fetched_at=fetched,
                       period_end=f'{annual_year-1}-12-31' if december else None,
                       period_type='전기말 · 당기 기초자본', role='opening_equity')
        opening_equity.append(opening)
    return {'schema_version': 2, 'code': code, 'name': company.get('corp_name', code),
            'asof': asof.isoformat(), 'fetched_at': fetched, 'basis': basis, 'rows': evidence,
            'opening_equity': opening_equity,
            'verification': 'API 구조·단위·중복·재무상태표 등식 점검. 원문 및 실제 API 대조 완료를 뜻하지 않습니다.',
            'data_gaps': [{'year': r['year'], 'report_code': r['report_code'], 'metric': r['metric'], 'reason': r['data_gap']}
                          for r in evidence + opening_equity if r['data_gap']]}
