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
    esc = lambda value: html.escape(str(value or '미확인'))
    rows = []
    for item in items:
        first = f"<td><strong>{esc(item['name'])}</strong><small>{esc(item['code'])}</small></td>"
        if item['result']:
            cells = []
            for index, original in enumerate((0, 1, 3, 2, 4, 5)):
                check = item['result']['checks'][original]
                text, state = cell(check, index)
                cells.append(f'<td><span class="sc-{state}" title="{esc(check["reason"])}">{esc(text)}</span></td>')
            body = ''.join(cells)
        else:
            body = f'<td colspan="6" class="sc-pending">{esc(item["reason"])}</td>'
        rows.append('<tr>' + first + body + '</tr>')
    return '''<style>
    .sc-wrap{overflow-x:auto;background:#fff;border:1px solid #dce3dc;border-radius:8px;margin:14px 0}
    .sc-table{border-collapse:collapse;width:100%;min-width:950px;font-size:16px}
    .sc-table th{background:#eef3ef;color:#183b30;text-align:left;padding:18px 14px;white-space:nowrap}
    .sc-table td{padding:22px 14px;border-top:1px solid #e3e8e3;vertical-align:middle}
    .sc-table small{display:block;color:#637267;margin-top:5px}.sc-table strong{font-size:18px}
    .sc-met,.sc-unmet,.sc-pending{font-weight:600}.sc-met{color:#236445}.sc-unmet{color:#a63742}.sc-pending{color:#6c706e}
    </style><div class="sc-wrap"><table class="sc-table"><thead><tr><th>종목</th>''' + ''.join(
        '<th>' + label + '</th>' for label in LABELS) + '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>'
