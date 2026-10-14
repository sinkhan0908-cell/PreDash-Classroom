"""Comparable public strategy results; no account data or network calls."""
import html

from predash.financial_validation import strategy_checks

LABELS = ('매출 CAGR', 'EPS CAGR', '5년 ROE 중앙값', 'PEG', '영업이익', '영업현금흐름')


def comparison_group(data):
    years = [r['year'] for r in data.get('rows', [])
             if r.get('report_code') == '11011' and r.get('period_type') == '연간']
    if not years:
        return None
    latest = max(years)
    currencies = {r.get('currency') for r in data.get('rows', []) if r.get('value') is not None}
    currency = 'KRW' if currencies == {'KRW'} else '통화 확인 필요'
    return f'{latest-4}~{latest}년 · {data.get("basis", "미확인")} · {currency}'


def build_comparison(codes, snapshots, quotes, names, unavailable, group, today):
    output = []
    for code in codes:
        data = snapshots.get(code)
        item = {'code': code, 'name': (data or {}).get('name') or names.get(code, code),
                'group': comparison_group(data) if data else None,
                'fetched_at': (data or {}).get('fetched_at'), 'result': None, 'reason': None,
                'quote': quotes.get(code, {})}
        if not data:
            item['reason'] = unavailable.get(code) or '재무자료 조회 전'
        elif unavailable.get(code):
            item['reason'] = unavailable[code]
        elif not item['group'] or '통화 확인 필요' in item['group']:
            item['reason'] = '비교 기간·통화 확인 필요'
        elif item['group'] != group:
            item['reason'] = '선택한 기간·회계 기준과 달라 비교 제외'
        else:
            quote = item['quote']
            item['result'] = strategy_checks(data, quote.get('close'), quote.get('date'),
                                              quote.get('source'), evaluation_date=today)
            # The comparison header promises the same five annual sales points.
            last = max(r['year'] for r in data['rows'] if r.get('report_code') == '11011' and r.get('period_type') == '연간')
            sales_years = {r['year'] for r in data['rows'] if r.get('report_code') == '11011'
                           and r.get('metric') == '매출' and r.get('value') is not None}
            if sales_years != set(range(last - 4, last + 1)):
                check = item['result']['checks'][0]
                if check['status'] != '판정 보류':
                    summary = item['result']['summary']
                    summary['completed'] -= 1
                    summary['met' if check['status'] == '충족' else 'unmet'] -= 1
                    summary['categories']['데이터 부족'] += 1
                    reason = '같은 비교 기간의 연속 5개 연간 매출 필요'
                    check.update(value=None, status='판정 보류', display_status='데이터 부족', reason_type='데이터 부족', reason=reason)
                    check['evidence'].update(result=None, blocked_reason=reason)
        output.append(item)
    return output


def cell(check, index):
    if check['status'] == '판정 보류':
        return check['display_status'], 'pending'
    state = 'met' if check['status'] == '충족' else 'unmet'
    if index < 3:
        value = f"{check['value']:.2f}%"
    elif index == 3:
        value = f"{check['value']:.2f}배"
    else:
        value = '5년 모두 양수' if state == 'met' else '0 이하 연도 있음'
    return value + ' · ' + check['display_status'], state


def table_html(items):
    esc = lambda value: html.escape(str(value if value is not None else '미확인'))
    rows = []
    short_names = {'005930': '삼성전자', '000660': 'SK하이닉스', '214450': '파마리서치'}
    thresholds = ('5개 결산점 · 0% 초과', '최근 4년 · 0% 초과', '중앙값 15% 이상', '1배 이하', '5년 연속 양수', '5년 연속 양수')
    for item in items:
        name = short_names.get(item['code'], item['name'])
        first = f'<th scope="row" class="sc-company" title="{esc(item["name"])}"><strong>{esc(name)}</strong><small>{esc(item["code"])}</small></th>'
        if item['result']:
            cells = []
            for index, original in enumerate((0, 1, 3, 2, 4, 5)):
                check = item['result']['checks'][original]
                text, state = cell(check, index)
                if check['status'] == '판정 보류':
                    value, label = '—', check['display_status']
                else:
                    value, label = text.rsplit(' · ', 1)
                value_class = 'sc-value sc-words' if index >= 4 else 'sc-value'
                cells.append(f'<td title="{esc(check["reason"])}"><span class="{value_class}">{esc(value)}</span><span class="sc-badge sc-{state}">{esc(label)}</span></td>')
            body = ''.join(cells)
        else:
            body = f'<td colspan="6" class="sc-empty"><span class="sc-badge sc-pending">확인 필요</span><p>{esc(item["reason"])}</p></td>'
        rows.append('<tr>' + first + body + '</tr>')
    headers = ''.join(f'<th scope="col">{label}<small>{hint}</small></th>' for label, hint in zip(LABELS, thresholds))
    return '''<style>
    .sc-wrap{overflow-x:auto;background:#fff;border:1px solid #dfe7e2;border-radius:16px;margin:18px 0 10px;box-shadow:0 3px 16px #183b3006}
    .sc-table{border-collapse:separate;border-spacing:0;width:100%;min-width:1110px;table-layout:fixed;font-size:15px;color:#20372f}
    .sc-table th,.sc-table td{box-sizing:border-box;text-align:center}
    .sc-table thead th{background:#f1f6f3;color:#254b3b;padding:21px 10px;font-size:15px;font-weight:700;white-space:nowrap;border-bottom:1px solid #dfe7e2}
    .sc-table thead th:first-child{width:210px;text-align:left;padding-left:24px}
    .sc-table thead small{display:block;color:#708178;font-size:11px;font-weight:400;margin-top:7px;line-height:1.5}
    .sc-table tbody td,.sc-table tbody th{padding:25px 10px;border-bottom:1px solid #e8eeea;vertical-align:middle;background:#fff}
    .sc-table tbody tr:last-child>*{border-bottom:0}
    .sc-table tbody tr:nth-child(even)>*{background:#fafcfb}
    .sc-table tbody tr:hover>*{background:#f3f8f5}
    .sc-table .sc-company{text-align:left;padding-left:24px;position:sticky;left:0;z-index:1;border-right:1px solid #e8eeea}
    .sc-company strong{display:block;font-size:18px;line-height:1.5;word-break:keep-all;overflow-wrap:anywhere;font-weight:700}
    .sc-company small{display:block;color:#809087;font-size:12px;letter-spacing:1px;font-weight:400;margin-top:6px}
    .sc-value{display:block;font-size:23px;font-weight:700;letter-spacing:-.5px;font-variant-numeric:tabular-nums;white-space:nowrap;line-height:1.4;margin-bottom:10px}
    .sc-value.sc-words{font-size:14px;letter-spacing:-.3px}
    .sc-badge{display:inline-block;border-radius:6px;padding:5px 9px;font-size:12px;line-height:1.3;white-space:nowrap;font-weight:600}
    .sc-met{background:#e8f4ec;color:#256643}.sc-unmet{background:#fbecef;color:#a63e51}.sc-pending{background:#edf0f2;color:#5a6870}
    .sc-empty{text-align:left!important;color:#68766e;font-size:14px}.sc-empty p{margin:9px 0 0}
    .sc-note{font-size:12px;color:#7c8982;margin-bottom:20px}
    </style><div class="sc-wrap" role="region" aria-label="관심종목 전략 비교표" tabindex="0"><table class="sc-table"><thead><tr><th scope="col">기업<small>종목명 · 종목코드</small></th>''' + headers + '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div><div class="sc-note">매출·EPS CAGR: 연평균 성장률 · 화면이 좁으면 표를 좌우로 이동하세요. 판정 사유는 아래 계산 근거에서 확인할 수 있습니다.</div>'
