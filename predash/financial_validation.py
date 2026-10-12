"""Public financial evidence only; API consistency checks are not an audit."""
import calendar
import math
import re
import statistics
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
VERIFICATION_TEXT = 'DART API 수집·자동 점검 완료. 전체 항목의 수동 원문 대조는 미완료입니다.'


def collection_status(value, reason=None):
    if value is not None and not reason:
        return 'DART 수집 정상'
    if reason and any(word in reason for word in ('서로 다름', '불일치', '통화', '혼재', '원문')):
        return '확인 필요'
    return '자료 부족'


def quote_date_check(asof, quote_date, receipt=None, max_age_days=7):
    """A dated recent close is usable; this does not assert it is the latest market close."""
    try:
        reference = date.fromisoformat(asof)
        closing = date.fromisoformat(quote_date)
    except (TypeError, ValueError):
        return '종가 또는 조회 기준일 형식 확인 필요', None
    age = (reference - closing).days
    if age < 0:
        return '종가 기준일이 조회일 이후: 날짜 불일치 확인 필요', age
    if age > max_age_days:
        return f'종가가 {age}일 이전 자료: 허용 범위 {max_age_days}일 초과, 시세 재조회 필요', age
    if receipt and re.fullmatch(r'\d{14}', str(receipt)):
        published = date(int(receipt[:4]), int(receipt[4:6]), int(receipt[6:8]))
        if closing < published:
            return '종가가 사용한 연간 EPS 공시 전 날짜: 시점 불일치 확인 필요', age
    return None, age


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
                       'status': collection_status(value, reason),
                       'data_gap': reason})
    by_name = {r['metric']: r for r in output}
    balance = [by_name[k]['value'] for k in ('자산총계', '부채총계', '자본총계')]
    if all(v is not None for v in balance) and abs(balance[0] - balance[1] - balance[2]) > max(1, abs(balance[0]) * 1e-9):
        for name in ('자산총계', '부채총계', '자본총계', '지배주주자본'):
            by_name[name].update(value=None, status='확인 필요', data_gap='자산 = 부채 + 자본 불일치: 원문 대조 필요')
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
            'verification': VERIFICATION_TEXT,
            'data_gaps': [{'year': r['year'], 'report_code': r['report_code'], 'metric': r['metric'], 'reason': r['data_gap']}
                          for r in evidence + opening_equity if r['data_gap']]}


def strategy_checks(data, quote=None, quote_date=None, quote_source=None):
    """Rule-based research leads; thresholds are dashboard settings, not investor quotes."""
    annual = {}
    issues = []
    if data.get('data_gaps'):
        issues.extend(g['reason'] for g in data['data_gaps'])
    for row in data.get('rows', []):
        if row.get('period_type') == '연간' or row.get('metric') in ('부채총계', '자본총계', '지배주주자본'):
            annual.setdefault(row['year'], {})[row['metric']] = row.get('value')
    years = sorted(y for y, values in annual.items() if '매출' in values or '지배주주순이익' in values)
    opening = {r.get('year'): r for r in data.get('opening_equity', [])}
    checks = []

    def add(group, label, value, unit, condition, period, sources, pending=None):
        if pending:
            metrics = ('기본 EPS',) if 'EPS' in label or 'PEG' in label else (
                ('지배주주순이익', '지배주주자본', '기초 지배주주자본') if 'ROE' in label else
                ('매출',) if '매출' in label else ('영업현금흐름',) if '현금흐름' in label else ('영업이익',))
            conflicts = [g['reason'] for g in data.get('data_gaps', [])
                         if g.get('metric') in metrics and g.get('report_code') == '11011'
                         and any(word in g['reason'] for word in ('서로 다름', '불일치', '통화', '혼재'))]
            if conflicts:
                pending = '원문 확인 필요 · ' + ' / '.join(dict.fromkeys(conflicts))
        if pending:
            status, reason = '판정 보류', pending
        elif value is None:
            status, reason = '판정 보류', '계산에 필요한 값이 부족합니다.'
        else:
            status = '충족' if condition else '미충족'
            if 'ROE' in label:
                reason = f'ROE 중앙값 {value:.2f}% · 기준 15% 이상'
            elif 'PEG' in label:
                reason = f'PEG {value:.2f} · 기준 1 이하'
            elif 'CAGR' in label:
                reason = f'연평균 성장률 {value:+.2f}% · 기준 0% 초과'
            else:
                reason = f'5년 중 최저 연간 금액 {value/1e8:,.2f}억원 · 기준 매년 0원 초과'
        category = '계산 완료'
        if status == '판정 보류':
            if any(word in reason for word in ('원문', '출처', '불일치', '통화')):
                category = '원문 확인 필요'
            elif any(word in reason for word in ('적자', '0 EPS', '양수가 아니', '비양수')):
                category = '공식 적용 불가'
            else:
                category = '데이터 부족'
        checks.append({'group': group, 'condition': label, 'value': value, 'unit': unit,
                       'status': status, 'display_status': category if status == '판정 보류' else status,
                       'reason_type': category, 'reason': reason, 'period': period, 'sources': sources})

    sales = [(y, annual[y].get('매출')) for y in years]
    sales = [(y, v) for y, v in sales if v is not None]
    sources = [r.get('source') for r in data.get('rows', []) if r.get('metric') == '매출' and r.get('period_type') == '연간']
    if len(sales) >= 2 and sales[0][1] > 0 and sales[-1][1] > 0:
        cagr = ((sales[-1][1] / sales[0][1]) ** (1 / (sales[-1][0] - sales[0][0])) - 1) * 100
        gap = None if len(sales) == sales[-1][0] - sales[0][0] + 1 else '연속 연간 매출 자료 부족'
    else:
        cagr = None
        gap = '연간 매출 자료 부족' if len(sales) < 2 else '연간 매출이 비양수여서 CAGR 계산 불가'
    add('린치 참고', f'매출 CAGR 양수 · {len(sales)}개 결산점', cagr, '%', cagr is not None and cagr > 0,
        f"{sales[0][0]}~{sales[-1][0]} 연간" if sales else None, sources, gap)

    eps_periods = years[-4:]
    eps = [(y, annual.get(y, {}).get('기본 EPS')) for y in eps_periods]
    eps_gap = None
    eps_cagr = None
    if len(eps) != 4 or any(v is None for _, v in eps):
        eps_gap = '연속 4개 연간 EPS 필요'
    elif any(eps[i][0] + 1 != eps[i + 1][0] for i in range(len(eps) - 1)):
        eps_gap = '연속 4개 연간 EPS 필요'
    elif any(v <= 0 for _, v in eps):
        eps_gap = '적자 또는 0 EPS가 포함되어 CAGR·PEG 계산 보류'
    else:
        eps_cagr = ((eps[-1][1] / eps[0][1]) ** (1 / (eps[-1][0] - eps[0][0])) - 1) * 100
    eps_sources = [r.get('source') for r in data.get('rows', []) if r.get('metric') == '기본 EPS' and r.get('year') in eps_periods]
    add('린치 참고', 'EPS CAGR 양수 · 최근 4개 연간 EPS', eps_cagr, '%', eps_cagr is not None and eps_cagr > 0,
        f"{eps_periods[0]}~{eps_periods[-1]} 연간" if eps_periods else None, eps_sources, eps_gap)

    latest_eps = annual.get(years[-1], {}).get('기본 EPS') if years else None
    per = quote / latest_eps if quote and latest_eps and latest_eps > 0 else None
    peg = per / eps_cagr if per is not None and eps_cagr is not None and eps_cagr > 0 else None
    quote_gap, quote_age = None, None
    if eps_gap:
        quote_gap = eps_gap
    elif not eps_cagr or eps_cagr <= 0:
        quote_gap = 'EPS CAGR이 양수가 아니어서 PEG 계산 불가'
    elif not quote or not quote_date:
        quote_gap = '같은 화면의 종가 또는 기준일 확인 필요'
    elif not quote_source:
        quote_gap = '종가 원문 출처 미확인'
    elif not latest_eps or latest_eps <= 0:
        quote_gap = '최근 연간 EPS가 비양수 또는 누락'
    else:
        eps_receipt = next((r.get('receipt') for r in data.get('rows', [])
                            if r.get('year') == years[-1] and r.get('metric') == '기본 EPS'
                            and r.get('report_code') == '11011'), None)
        quote_gap, quote_age = quote_date_check(data.get('asof'), quote_date, eps_receipt)
    quote_sources = list(dict.fromkeys([quote_source] + eps_sources)) if quote_source else eps_sources
    add('린치 참고', 'PEG ≤ 1 · 기준일 종가 ÷ 최근 연간 EPS ÷ EPS CAGR(%)', peg, '배수', peg is not None and peg <= 1,
        f"종가 {quote_date or '미확인'} / EPS {years[-1] if years else '미확인'}년", quote_sources, quote_gap)
    if quote_age is not None and not quote_gap:
        checks[-1]['reason'] += f' · {quote_date} 종가 기준 · 조회일 대비 {quote_age}일 이전'

    recent = years[-5:]
    roes, roe_gap, roe_sources = [], None, []
    for y in recent:
        p = annual.get(y, {})
        beginning = opening.get(y, {})
        end_equity = p.get('지배주주자본')
        begin_equity = beginning.get('value')
        if not beginning or beginning.get('data_gap') or begin_equity is None or end_equity is None or p.get('지배주주순이익') is None:
            roe_gap = f'{y}년 이익 또는 기초·기말 지배주주자본 누락'
            break
        if begin_equity <= 0 or end_equity <= 0:
            roe_gap = f'{y}년 기초 또는 기말 지배주주자본 비양수'
            break
        roes.append(100 * p['지배주주순이익'] / ((begin_equity + end_equity) / 2))
        roe_sources.extend([beginning.get('source')] + [r.get('source') for r in data.get('rows', [])
                            if r.get('year') == y and r.get('metric') in ('지배주주자본', '지배주주순이익')])
    if len(recent) != 5 or (recent and recent[-1] - recent[0] != 4):
        roe_gap = '연속 5개 연간 재무자료 필요'
    median_roe = statistics.median(roes) if len(roes) == 5 and not roe_gap else None
    add('버핏 참고', '5년 ROE 중앙값 ≥ 15% · 지배주주순이익/평균 지배주주자본', median_roe, '%',
        median_roe is not None and median_roe >= 15, f'{recent[0]}~{recent[-1]} 연간' if recent else None,
        list(dict.fromkeys(roe_sources)), roe_gap)

    def all_positive(metric, label):
        vals = [(y, annual.get(y, {}).get(metric)) for y in recent]
        missing = [y for y, v in vals if v is None]
        value = min((v for _, v in vals), default=None) if not missing else None
        gap = f'{missing[0]}년 {metric} 누락' if missing else ('연속 5개 연간 자료 부족' if len(recent) != 5 or (recent and recent[-1] - recent[0] != 4) else None)
        src = [r.get('source') for r in data.get('rows', []) if r.get('year') in recent and r.get('metric') == metric]
        add('버핏 참고', label, value, '원', value is not None and value > 0,
            f'{recent[0]}~{recent[-1]} 연간' if recent else None, src, gap)
    all_positive('영업이익', '최근 5년 영업이익 모두 양수')
    all_positive('영업현금흐름', '최근 5년 영업현금흐름 모두 양수')

    latest = annual.get(years[-1], {}) if years else {}
    debt, equity = latest.get('부채총계'), latest.get('자본총계')
    debt_ratio = debt / equity * 100 if debt is not None and equity is not None and equity > 0 else None
    fcf = None
    capex = latest.get('유형자산 취득'), latest.get('무형자산 취득')
    if latest.get('영업현금흐름') is not None and all(v is not None for v in capex):
        fcf = latest['영업현금흐름'] - sum(capex)
    summary = {'total': len(checks), 'completed': sum(c['reason_type'] == '계산 완료' for c in checks),
               'met': sum(c['status'] == '충족' for c in checks), 'unmet': sum(c['status'] == '미충족' for c in checks),
               'categories': {category: sum(c['reason_type'] == category for c in checks)
                              for category in ('데이터 부족', '공식 적용 불가', '원문 확인 필요')},
               'annual_period': f'{years[0]}~{years[-1]}년 연간' if years else '연간 자료 없음'}
    return {'rule_version': 2, 'code': data.get('code'), 'financial_fetched_at': data.get('fetched_at'),
            'evaluated_at': datetime.now(ZoneInfo('Asia/Seoul')).isoformat(timespec='seconds'),
            'quote_input': {'close': quote, 'date': quote_date, 'source': quote_source,
                            'age_calendar_days': quote_age, 'max_age_calendar_days': 7,
                            'basis': '표시된 날짜 종가 기준 · 최신 거래일 여부 미확인'},
            'checks': checks, 'summary': summary, 'reference_metrics': {'latest_annual_year': years[-1] if years else None,
            'debt_to_equity_pct': debt_ratio, 'simple_fcf_won': fcf,
            'reference_period': f'{years[-1]} 연간' if years else None},
            'note': '대시보드 자체 조사 기준이며 대가의 공식·추천이 아닙니다. 정성 요인 및 공시 원문 검증은 별도입니다.'}


def export_validation(data, strategy=None):
    """Export the displayed public financial snapshot and its matching calculation."""
    payload = dict(data)
    payload['schema_version'] = 3
    payload['verification'] = VERIFICATION_TEXT
    if data.get('data_gaps'):
        payload['verification'] = 'DART API 수집·자동 점검 수행. 예외 항목은 data_gaps를 확인하세요. 전체 항목의 수동 원문 대조는 미완료입니다.'
    matches = strategy is not None and strategy.get('code') == data.get('code') and strategy.get('financial_fetched_at') == data.get('fetched_at')
    payload['strategy_result'] = strategy if matches else None
    payload['strategy_export_status'] = '전략 계산 결과 포함' if matches else '전략 계산 전' if strategy is None else '재무자료와 결과 시점 불일치 · 재계산 필요'
    payload['exported_at'] = datetime.now(ZoneInfo('Asia/Seoul')).isoformat(timespec='seconds')
    return payload
