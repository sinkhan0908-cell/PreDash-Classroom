import sys,types,unittest,json,ast
try:import requests
except ImportError:sys.modules['requests']=types.SimpleNamespace(RequestException=Exception,request=None)
from copy import deepcopy
from datetime import date
from unittest.mock import patch,MagicMock
from predash.valuation_evidence import describe,references
from predash.lynch_kis import calculate_reference
from predash.lynch_view import metrics,table,number
from predash.lynch import BS,SOURCE
from tests_lynch_ui import functions
from predash.financial_freshness import fingerprint

class ValuationEvidenceTests(unittest.TestCase):
    def setUp(self):
        rows=[{'metric':'KIS EPS','year':y,'period_end':f'{y}-12-31','value':v,'unit':'원/주','basis':'KIS 회계 기준 미확인','report_code':'11011','period_type':'연간','source':'https://apiportal.koreainvestment.com/','receipt':None} for y,v in zip(range(2021,2026),(5777,8057,2131,4950,6564))]
        self.saved={'source':'KIS','data':{'code':'005930','name':'삼성전자','basis':'KIS 회계 기준 미확인','fetched_at':'2026-10-16T16:29:32+09:00','rows':rows,'lynch':{'eps_comparability_gaps':[]}},'quote':{'close':210000,'date':'2026-10-15','source':'KIS 모의 일별 시세','kind':'종가'}}
        self.raw=calculate_reference(self.saved,date(2026,10,16))
    def test_reported_32_is_annual_not_ttm_and_mismatch_retains_original_inputs(self):
        before=deepcopy(self.saved)
        result=describe(self.saved,self.raw,'2026-10-16')
        self.assertAlmostEqual(result['per'],210000/6564)
        self.assertAlmostEqual(result['peg'],result['per']/result['cagr'])
        self.assertEqual(result['valuation_basis']['per_label'],'2025년 연간 EPS 기준 PER')
        self.assertIsNone(result['valuation_basis']['ttm_per'])
        comparison=result['eps_crosscheck']['comparisons'][0]
        self.assertEqual((comparison['provider_eps'],comparison['reference_eps'],comparison['difference']),(6564,6605,-41))
        self.assertEqual(comparison['status'],'numeric_mismatch')
        self.assertIsNone(comparison['definition_match'])
        self.assertEqual(result['verification']['valuation_status'],'reference_only_mismatch')
        self.assertEqual(self.saved,before);self.assertNotIn('valuation_basis',self.raw)
    def test_matching_number_does_not_verify_unknown_kis_accounting_definition(self):
        self.saved['data']['rows'][-1]['value']=6605
        result=describe(self.saved,self.raw,'2026-10-16')
        self.assertEqual(result['eps_crosscheck']['status'],'partial_numeric_match')
        self.assertEqual(result['eps_crosscheck']['definition_status'],'unverified')
        self.assertEqual(result['eps_crosscheck']['compared_years'],1)
        self.assertEqual(result['eps_crosscheck']['input_years'],5)
        self.assertEqual(result['verification']['valuation_status'],'reference_only')
    def test_unknown_company_period_and_unit_never_get_reference_confirmation(self):
        for case in ('code','period','unit'):
            value=deepcopy(self.saved)
            if case=='code':value['data']['code']='000660'
            elif case=='period':value['data']['rows'][-1]['period_end']='2025-03-31'
            else:value['data']['rows'][-1]['unit']='USD/share'
            self.assertEqual(describe(value,self.raw,'2026-10-16')['eps_crosscheck']['status'],'not_checked')
    def test_separate_statements_not_compared_to_consolidated_reference(self):
        self.saved['source']='DART';self.saved['data']['basis']='OFS'
        for r in self.saved['data']['rows']:r.update(metric='기본 EPS',basis='OFS')
        self.assertEqual(describe(self.saved,self.raw,'2026-10-16')['eps_crosscheck']['status'],'not_checked')
    def test_future_and_conflicting_reference_rows_fail_closed(self):
        refs=references();future=deepcopy(refs);future[0]['checked_on']='2026-10-17'
        for values in (future,refs+refs,[]):
            self.assertEqual(describe(self.saved,self.raw,'2026-10-16',values)['eps_crosscheck']['status'],'not_checked')
    def test_reference_read_failure_does_not_hide_results_or_claim_verification(self):
        with patch('predash.valuation_evidence.REFERENCE_PATH') as path:
            path.read_text.side_effect=OSError('missing')
            result=describe(self.saved,self.raw,'2026-10-16')
        self.assertEqual(result['eps_crosscheck']['status'],'not_checked')
        self.assertAlmostEqual(result['per'],self.raw['per'])
    def test_invalid_price_per_and_peg_remain_null(self):
        self.raw.update(per=None,peg=None,price_gap='날짜 미확인')
        result=describe(self.saved,self.raw,'2026-10-16')
        self.assertIsNone(result['per']);self.assertIsNone(result['peg'])
    def test_visible_warning_and_export_include_dated_comparison_without_replacing_api_eps(self):
        st=MagicMock();st.session_state={}
        ns=functions(['lynch_results','lynch_options'],dict(st=st,describe_lynch_valuation=describe,calculate_kis_reference=calculate_reference,json=json,
            lynch_metrics=metrics,lynch_table=table,lynch_number=number,financial_fingerprint=fingerprint,LYNCH_BS=BS,LYNCH_SOURCE=SOURCE))
        ns['lynch_results'](self.saved,date(2026,10,16))
        self.assertTrue(any('EPS 공시 수치 불일치' in str(c) for c in st.warning.call_args_list))
        self.assertTrue(any('2025년 연간 EPS 기준 PER' in str(c) for c in st.html.call_args_list))
        exported=json.loads(st.download_button.call_args.args[1])
        self.assertEqual(exported['financial']['rows'][-1]['value'],6564)
        self.assertEqual(exported['analysis']['eps_crosscheck']['comparisons'][0]['checked_on'],'2026-10-16')
        self.assertIn('2025_con_quarter04_all.pdf',exported['analysis']['eps_crosscheck']['comparisons'][0]['source'])
        self.assertIsNone(exported['analysis']['valuation_basis']['ttm_per'])
