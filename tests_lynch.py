import unittest
from copy import deepcopy
from tests_strategy_evidence import fixture
from predash.lynch import analyse, balance_rows, cards_html

class LynchTests(unittest.TestCase):
    def setUp(self):
        self.data=fixture()
        self.data['name']='공개기업'
        self.data['lynch']={'eps_comparability_gaps':[]}
        self.quote={'close':1600,'date':'2026-10-14','source':'KIS'}
    def calc(self): return analyse(self.data,self.quote,'2026-10-15')
    def test_cagr_uses_four_intervals_and_peg_percentage_number(self):
        r=self.calc(); h=r['history']
        expected=((h[-1]['value']/h[0]['value'])**.25-1)*100
        self.assertAlmostEqual(r['cagr'],expected)
        self.assertAlmostEqual(r['per'],1600/h[-1]['value'])
        self.assertAlmostEqual(r['peg'],r['per']/expected)
    def test_negative_middle_blocks_cagr_but_keeps_transitions(self):
        next(r for r in self.data['rows'] if r['metric']=='기본 EPS' and r['year']==2023)['value']=-10
        r=self.calc()
        self.assertIsNone(r['cagr']); self.assertIsNone(r['peg'])
        self.assertIn('흑자 전환',[r['note'] for r in r['history']])
        self.assertIn('적자 전환',[r['note'] for r in r['history']])
    def test_comparative_restatement_blocks_growth_not_per(self):
        self.data['lynch']['eps_comparability_gaps']=['비교 EPS 불일치']
        r=self.calc(); self.assertIsNone(r['peg']); self.assertIsNotNone(r['per'])
    def test_stale_missing_source_or_future_quote_does_not_produce_per(self):
        for q in ({'close':1600,'date':'2026-10-01','source':'KIS'}, {'close':1600,'date':'2026-10-16','source':'KIS'}, {'close':1600,'date':'2026-10-14'}):
            self.quote=q
            self.assertIsNone(self.calc()['per']); self.assertIsNotNone(self.calc()['cagr'])
    def test_incomplete_years_not_annualised_with_wrong_interval(self):
        self.data['rows']=[r for r in self.data['rows'] if r['year']!=2022]
        self.assertIsNone(self.calc()['cagr'])
    def test_cash_and_debt_missing_not_zero_and_conflicts_not_summed(self):
        raw=[{'sj_div':'BS','account_id':'ifrs-full_CashAndCashEquivalents','currency':'KRW','thstrm_amount':'100'}]
        r=balance_rows(raw)
        self.assertEqual(r['현금및현금성자산']['value'],100)
        self.assertIsNone(r['장기차입금']['value'])
        raw.append({**raw[0],'thstrm_amount':'200'})
        self.assertIsNone(balance_rows(raw)['현금및현금성자산']['value'])
    def test_high_growth_not_labelled_failed_and_html_escaped(self):
        for row in self.data['rows']:
            if row['metric']=='기본 EPS': row['value']=100*2**(row['year']-2021)
        r=self.calc(); self.assertIn('지속 가능성',r['reference'])
        r['reference']='<script>x</script>'
        self.assertNotIn('<script>',cards_html(r))
    def test_collector_keeps_same_report_basis_sources_and_missing_debt(self):
        from unittest.mock import Mock,patch
        from predash.lynch import collect_lynch
        from datetime import date
        provider=Mock();provider.corp.return_value='00126380'
        values={r['year']:r['value'] for r in self.data['rows'] if r['metric']=='기본 EPS'}
        def dart(endpoint,**kw):
            year=int(kw['bsns_year'])
            common={'currency':'KRW','rcept_no':f'{year+1}0301000001','bsns_year':str(year),'reprt_code':'11011'}
            return {'list':[{**common,'sj_div':'IS','account_id':'ifrs-full_BasicEarningsLossPerShare','thstrm_amount':str(values[year]),'frmtrm_amount':str(values.get(year-1,10))},
                            {**common,'sj_div':'BS','account_id':'ifrs-full_CashAndCashEquivalents','thstrm_amount':'100'}]}
        provider.dart.side_effect=dart
        with patch('predash.lynch.collect',return_value=self.data):
            output=collect_lynch(provider,'005930',date(2026,10,15))
        self.assertEqual(output['lynch']['eps_comparability_gaps'],[])
        current=output['lynch']['balances'][1]
        self.assertEqual(current['date'],'2025-12-31')
        self.assertIn('rcpNo=',current['source'])
        self.assertEqual(current['accounts']['현금및현금성자산']['value'],100)
        self.assertIsNone(current['accounts']['단기차입금']['value'])
    def test_page_renders_three_sections_and_exports_public_evidence(self):
        import ast,json,re
        from pathlib import Path
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from unittest.mock import MagicMock
        from predash.lynch import analyse,cards_html,BS,SOURCE
        self.data['fetched_at']=datetime.now(ZoneInfo('Asia/Seoul')).isoformat()
        st=MagicMock()
        st.session_state={'watch_codes':['005930'],'watch_names':{},'lynch_data_005930':{'data':self.data,'quote':self.quote}}
        st.query_params={}
        st.selectbox.return_value='005930';st.button.return_value=False
        ns=dict(lynch_freshness_panel=MagicMock(),lynch_restore_saved=MagicMock(),lynch_save_remote=MagicMock(),st=st,datetime=datetime,ZoneInfo=ZoneInfo,clean_codes=lambda codes:[c for c in codes if c],re=re,json=json,
                analyse_lynch=analyse,lynch_cards_html=cards_html,LYNCH_BS=BS,LYNCH_SOURCE=SOURCE)
        node=next(n for n in ast.parse(Path('app.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='lynch_page')
        exec(compile(ast.Module(body=[node],type_ignores=[]),'app.py','exec'),ns)
        ns['lynch_page']()
        sections=[c.args[0] for c in st.subheader.call_args_list]
        for title in ['01  이익 성장','02  성장 대비 가격','03  재무 상태']: self.assertIn(title,sections)
        exported=json.loads(st.download_button.call_args.args[1])
        self.assertIn('financial',exported);self.assertNotIn('account',exported)
