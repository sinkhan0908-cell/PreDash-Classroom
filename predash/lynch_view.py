"""Compact, escaped presentation of existing Lynch calculations."""
from html import escape

STYLE='''<style>
.lynch-status{border:1px solid #e2e8f0;background:#f8fafc;border-radius:8px;padding:12px 16px;color:#526176;font-size:14px;line-height:1.7;margin:8px 0 20px}
.lynch-metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:10px 0 18px}
.lynch-metric{background:#fff;border:1px solid #dfe6ef;border-radius:9px;padding:20px 22px}
.lynch-metric small{display:block;color:#526176;font-size:14px;margin-bottom:8px}
.lynch-metric strong{display:block;color:#1746a2;font-size:30px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.2}
.lynch-scroll{overflow-x:auto;border:1px solid #dfe6ef;border-radius:8px;margin-bottom:22px}
.lynch-table{width:100%;border-collapse:collapse;background:#fff;font-size:15px;color:#233349;font-variant-numeric:tabular-nums}
.lynch-table th{background:#f3f6fa;color:#526176;font-weight:600;white-space:nowrap}
.lynch-table td,.lynch-table th{padding:12px 18px;text-align:right;border-bottom:1px solid #e9edf3}
.lynch-table td:first-child,.lynch-table th:first-child{text-align:left}
.lynch-table tr:last-child td{border-bottom:0}.lynch-table tbody tr:hover{background:#f8faff}

</style>'''


def number(value,suffix='',digits=1):
    return '미확인' if value is None else f'{value:,.{digits}f}'+suffix


def metrics(items):
    return STYLE+'<div class="lynch-metrics">'+''.join('<div class="lynch-metric"><small>'+escape(label)+'</small><strong>'+escape(value)+'</strong></div>' for label,value in items)+'</div>'


def table(headers,rows):
    return STYLE+'<div class="lynch-scroll"><table class="lynch-table"><thead><tr>'+''.join('<th>'+escape(str(c))+'</th>' for c in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+escape(str(c))+'</td>' for c in row)+'</tr>' for row in rows)+'</tbody></table></div>'


def status(saved,record=None,failed=False):
    data=saved['data'];quote=saved.get('quote',{})
    def day(value):
        return str(value)[5:10].replace('-','.') if value else '미확인'
    label='이전 자료 사용 · 확인 실패' if failed or (record or {}).get('status')=='failed' else '저장 자료 사용'
    checked=day((record or {}).get('checked_at'))
    if record and record.get('status')!='failed':
        checked+=' API 확인'
    source='KIS 참고값 · EPS 정의 원문 미대조' if saved.get('source')=='KIS' else 'DART'
    parts=[label,source,'재무 '+day(data.get('fetched_at'))+' 수집','API 변경 '+checked,quote.get('kind','종가')+' '+day(quote.get('date'))]
    return STYLE+'<div class="lynch-status">'+escape('　·　'.join(parts))+'</div>'


PAGE_STYLE='''<span class="lynch-page-marker" style="display:none"></span><style>
.stApp:has(.lynch-page-marker){--pd-ink:#15243e;--pd-muted:#627087;--pd-line:#e2e8f0;--pd-paper:#ffffff;--pd-base:#ffffff;background:#ffffff;color:#15243e;color-scheme:light}
.stApp:has(.lynch-page-marker) [data-testid="stHeader"]{background:rgba(255,255,255,.95)}
.stApp:has(.lynch-page-marker) [data-testid="stSidebar"]{background:#f7f9fc;border-color:#e2e8f0}
.stApp:has(.lynch-page-marker) [data-testid="stSidebar"] h1{color:#15243e}
.stApp:has(.lynch-page-marker) [data-testid="stSidebar"] [role="radiogroup"] label p{color:#526176}
.stApp:has(.lynch-page-marker) [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked){background:#eaf1ff;border-color:#2563eb}
.stApp:has(.lynch-page-marker) [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p{color:#1d4ed8}
.stApp:has(.lynch-page-marker) .stButton>button[kind="primary"]{background:#1759ed;border-color:#1759ed;border-radius:8px!important}
.stApp:has(.lynch-page-marker) .stButton>button[kind="primary"]:hover{background:#1746a2;border-color:#1746a2}
.stApp:has(.lynch-page-marker) [data-testid="stExpander"] details{border:1px solid #e2e8f0;border-radius:8px;background:#fff}
.stApp:has(.lynch-page-marker) [data-testid="stCaptionContainer"] p{font-size:14px}
</style>'''
