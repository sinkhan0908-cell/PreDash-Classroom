"""Lynch-inspired quantitative evidence. No overall pass, score or investment advice."""
import html
from datetime import datetime
from zoneinfo import ZoneInfo
from predash.financial_validation import collect, parse_statement, numeric, quote_date_check
from predash.official import DataError

VERSION = 1
SOURCE = 'https://www.simonandschuster.com/books/One-Up-On-Wall-Street/Peter-Lynch/9780743200400'
# Conservative exact matches. Never substitute total liabilities for borrowings.
BS = {
 '현금및현금성자산': ('ifrs-full_CashAndCashEquivalents', ('현금및현금성자산',)),
 '단기차입금': ('ifrs-full_ShorttermBorrowings', ('단기차입금',)),
 '유동성 장기차입금': (None, ('유동성장기차입금', '유동성장기부채')),
 '장기차입금': (None, ('장기차입금',)),
 '유동 사채': (None, ('유동성사채', '유동사채')),
 '비유동 사채': (None, ('사채', '비유동사채')),
}

def balance_rows(raw):
    output = {}
    for label, (account_id, names) in BS.items():
        found = [r for r in raw if r.get('sj_div') == 'BS' and
                 ((account_id and r.get('account_id') == account_id) or r.get('account_nm') in names)]
        values = [numeric(r.get('thstrm_amount')) for r in found]
        valid = bool(found) and all(r.get('currency') == 'KRW' for r in found) and all(v is not None for v in values) and len(set(values)) == 1
        output[label] = {'value': values[0] if valid else None,
                         'reason': None if valid else '계정 누락·중복 불일치·통화 확인 필요',
                         'accounts': [{'id': r.get('account_id'), 'name': r.get('account_nm')} for r in found]}
    return output


def collect_lynch(provider, code, asof=None):
    class CachedProvider:
        def __init__(self): self.raw = {}
        def corp(self, code): return provider.corp(code)
        def dart(self, endpoint, **kwargs):
            key = (endpoint, tuple(sorted(kwargs.items())))
            if key not in self.raw: self.raw[key] = provider.dart(endpoint, **kwargs)
            return self.raw[key]
    proxy = CachedProvider()
    data = collect(proxy, code, asof)
    latest = max(data['rows'], key=lambda r: (r['year'], {'11011':4,'11014':3,'11012':2,'11013':1}[r['report_code']]))
    corp = proxy.corp(code)
    year, report, basis = latest['year'], latest['report_code'], data['basis']
    balances = []
    for target_year in (year-1, year):
        try:
            raw = (proxy.dart('fnlttSinglAcntAll.json', corp_code=corp, bsns_year=str(target_year), reprt_code=report, fs_div=basis) or {}).get('list') or []
            parsed = parse_statement(raw, target_year, report, basis, data['asof'], bool(latest.get('period_end')))
            meta = next(r for r in parsed if r['metric'] == '자산총계')
            accounts = balance_rows(raw)
            if not meta['source'] or not meta['period_end'] or (meta['data_gap'] and '계정 누락' not in meta['data_gap']):
                for value in accounts.values(): value.update(value=None, reason=meta['data_gap'] or '기간·출처 미확인')
            balances.append({'year':target_year, 'date':meta['period_end'], 'source':meta['source'], 'accounts':accounts})
        except DataError as exc:
            balances.append({'year':target_year, 'date':None, 'source':None, 'error':str(exc), 'accounts':{}})
    # Detect adjacent filing changes; do not silently compare restated/split EPS vintages.
    eps_changes = []
    annual = sorted({r['year'] for r in data['rows'] if r['report_code']=='11011'})
    for target_year in annual[1:]:
        raw = (proxy.dart('fnlttSinglAcntAll.json', corp_code=corp, bsns_year=str(target_year), reprt_code='11011', fs_div=basis) or {}).get('list') or []
        comparative = [{**r, 'thstrm_amount':r.get('frmtrm_amount')} for r in raw]
        prior = next(r for r in parse_statement(comparative,target_year,'11011',basis,data['asof']) if r['metric']=='기본 EPS')
        original = next((r for r in data['rows'] if r['year']==target_year-1 and r['report_code']=='11011' and r['metric']=='기본 EPS'), {})
        if prior['value'] is None or original.get('value') is None:
            eps_changes.append(f'{target_year-1}년 EPS 전기 비교값 확인 불가')
        elif abs(prior['value']-original['value']) > max(.01, abs(original['value'])*1e-6):
            eps_changes.append(f'{target_year-1}년 EPS가 인접 공시 전기 비교값과 다름: 재작성·주당 단위 확인 필요')
    data['lynch'] = {'version':VERSION, 'balances':balances, 'eps_comparability_gaps':eps_changes}
    return data


def analyse(data, quote, today):
    annual = sorted([r for r in data['rows'] if r['metric']=='기본 EPS' and r['report_code']=='11011' and r['period_type']=='연간'],key=lambda r:r['year'])
    history=[]
    for i,row in enumerate(annual):
        prev=annual[i-1] if i else None
        value,prior=row['value'],prev['value'] if prev else None
        consecutive=bool(prev and row['year']==prev['year']+1)
        growth=(value/prior-1)*100 if consecutive and value is not None and prior is not None and prior>0 and value>=0 else None
        note='첫 연도' if not prev else '자료 부족'
        if consecutive and value is not None and prior is not None:
            note='흑자 전환' if prior<=0<value else '적자 전환' if prior>0>value else '적자·0 포함' if prior<=0 or value<=0 else '증가' if value>prior else '감소' if value<prior else '동일'
        history.append({**row,'growth':growth,'note':note})
    gaps=list(data.get('lynch',{}).get('eps_comparability_gaps',[]))
    if len(annual)!=5 or any(annual[i]['year']!=annual[0]['year']+i for i in range(len(annual))): gaps.append('연속 5개 연간 EPS 필요')
    if any(r['value'] is None or r['value']<=0 for r in annual): gaps.append('적자·0·누락 EPS 포함: CAGR·PEG 계산 제한')
    cagr=((annual[-1]['value']/annual[0]['value'])**.25-1)*100 if not gaps and annual else None
    reference='계산 보류' if cagr is None else '린치 선호 범위 20~25% 해당' if 20<=cagr<=25 else '25% 초과 · 지속 가능성 확인' if cagr>25 else '20% 미만 · 선호 범위 아래'
    recent=annual[-1] if annual else {}
    price_gap,age=quote_date_check(today,quote.get('date'),recent.get('receipt'))
    if not quote.get('source') or quote.get('close') is None or quote.get('close',0)<=0: price_gap='유효한 종가·출처 필요'
    eps=recent.get('value')
    per=quote['close']/eps if not price_gap and eps is not None and eps>0 else None
    peg=per/cagr if per is not None and cagr is not None and cagr>0 else None
    return {'history':history,'cagr':cagr,'reference':reference,'per':per,'peg':peg,'growth_gaps':gaps,
            'price_gap':price_gap,'price_age_days':age,'eps_year':recent.get('year'),'quote':quote,
            'evaluated_at':today,'financial_fetched_at':data['fetched_at']}


def cards_html(result):
    esc=lambda x:html.escape(str(x))
    fmt=lambda x,suffix:f'{x:,.2f}{suffix}' if x is not None else '—'
    return '''<style>
    .ly-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin:18px 0 24px}
    .ly-card{background:#fff;border:1px solid #dce5df;border-radius:14px;padding:24px;min-width:0}
    .ly-card small{color:#6c7f74;font-size:13px}.ly-card strong{display:block;color:#193f30;font-size:32px;font-weight:750;margin:12px 0}.ly-card p{font-size:14px;line-height:1.6;margin:0;color:#52675b}
    @media(max-width:850px){.ly-grid{grid-template-columns:1fr}}
    </style><div class="ly-grid">''' + ''.join(f'<div class="ly-card"><small>{esc(title)}</small><strong>{esc(value)}</strong><p>{esc(note)}</p></div>' for title,value,note in [
        ('01 · 이익 성장 / 4년 EPS CAGR',fmt(result['cagr'],'%'),result['reference']),
        ('02 · 가격 / 연간 EPS 기준 PER',fmt(result['per'],'배'),f"{result['eps_year']}년 EPS 기준 · 기준일 종가 사용"),
        ('성장 대비 가격 / 과거 PEG',fmt(result['peg'],'배'),'PER ÷ 과거 EPS CAGR(%) · 미래 성장 예측 아님')])+'</div>'
