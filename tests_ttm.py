import sys,types,unittest,json
try:import requests
except ImportError:sys.modules['requests']=types.SimpleNamespace(RequestException=Exception,request=None)
from copy import deepcopy
from datetime import date,datetime
from zoneinfo import ZoneInfo
from unittest.mock import Mock,MagicMock,patch
from predash.ttm import calculate,parse_samsung,parse_listing,collect_samsung,collect_dart,due,pdf_text,TtmError,ROOT,INDEX
from predash.financial_store import persist,select_snapshot,clean_snapshot
from predash.valuation_evidence import describe
from tests_lynch_ui import functions
import tests_financial_store as store_tests


def pages(y,q):
    # Narrow source-specific EPS layout fixture, based on the official reviewed notes.
    end={1:'March 31',2:'June 30',3:'September 30',4:'December 31'}[q]
    audit='February 12 '+str(y+1) if q==4 else 'August 13 '+str(y)
    head=f'SAMSUNG ELECTRONICS CO., LTD. AND ITS SUBSIDIARIES Consolidated Financial Statements {end}, {y} Seoul, Korea {audit}'
    if q==4:
        profits='38,901,477 29,547,625';shares='5,889,607 5,969,672';eps='6,605 4,950';columns=''
    else:
        profits='62,564,653 103,966,168 4,336,895 11,392,986';shares='5,767,030 5,791,848 5,881,154 5,903,847';eps='10,849 17,950 737 1,929';columns='3 Months 6 Months 3 Months 6 Months'
    note=f'''23. Earnings per Share
Earnings per share for the periods are calculated as follows:
(A) Ordinary shares
(1) Basic earnings per share
{y} {y-1}
(In millions of Korean won and thousands of number of shares) {columns}
Profit for the period attributable to ordinary shares {profits}
Weighted-average number of ordinary shares outstanding {shares}
Basic earnings per ordinary share (in Korean won) {eps}
(2) Diluted earnings per share
'''
    return [head,'','','',note]


def block():
    annual=parse_samsung(pages(2025,4),2025,4,ROOT+'2025_con_quarter04_all.pdf','annual-hash',date(2026,10,16))[0]
    current,prior=parse_samsung(pages(2026,2),2026,2,ROOT+'2026_con_quarter02_all.pdf','interim-hash',date(2026,10,16))
    return {'version':1,'status':'success','code':'005930','inputs':[annual,current,prior],'fetched_at':'2026-10-16T19:00:00+09:00','last_attempt_at':'2026-10-16T19:00:00+09:00'}


class TtmTests(unittest.TestCase):
    def setUp(self):
        self.block=block();self.today=date(2026,10,16)
        self.quote={'close':210000,'date':'2026-10-15','source':'KIS 모의 일별 시세','kind':'종가'}
    def test_samsung_ttm_uses_common_profit_and_share_days_not_eps_addition(self):
        result=calculate(self.block,self.quote,self.today)
        expected_profit=(38901477+103966168-11392986)*1e6
        expected_shares=(5889607*365+5791848*181-5903847*181)*1000/365
        self.assertAlmostEqual(result['profit'],expected_profit)
        self.assertAlmostEqual(result['weighted_shares'],expected_shares)
        self.assertAlmostEqual(result['eps'],expected_profit/expected_shares)
        self.assertAlmostEqual(result['per'],9.318557971473673)
        self.assertEqual((result['period_start'],result['period_end']),('2025-07-01','2026-06-30'))
        self.assertNotAlmostEqual(result['eps'],6605+17950-1929)
    def test_new_price_recalculates_per_without_changing_financial_dates(self):
        before=deepcopy(self.block)
        first=calculate(self.block,self.quote,self.today)
        second=calculate(self.block,{**self.quote,'close':215500},self.today)
        self.assertEqual(first['eps'],second['eps']);self.assertGreater(second['per'],first['per'])
        self.assertEqual(self.block,before)
    def test_annual_only_is_a_real_12month_window(self):
        self.block['inputs']=self.block['inputs'][:1]
        result=calculate(self.block,self.quote,self.today)
        self.assertIsNotNone(result['per']);self.assertEqual(result['period_end'],'2025-12-31')
    def test_missing_shares_mismatch_profit_wrong_basis_and_period_fail_closed(self):
        for case in ('shares','eps','basis','period','currency','split','comparison'):
            value=deepcopy(self.block);row=value['inputs'][1]
            if case=='shares':row['weighted_shares']=None
            elif case=='eps':row['profit']*=10
            elif case=='basis':row['basis']='OFS'
            elif case=='period':row['period_end']='2026-09-30'
            elif case=='currency':row['currency']='USD'
            elif case=='split':row['share_adjustment_flag']=True
            else:value['inputs'][2]['document_sha256']='different-vintage'
            self.assertIsNone(calculate(value,self.quote,self.today)['per'],case)
    def test_negative_ttm_profit_and_future_or_stale_price_do_not_produce_per(self):
        for case in ('negative','future','stale','lookahead'):
            value=deepcopy(self.block);quote=deepcopy(self.quote)
            if case=='negative':
                for r in value['inputs']:r['profit']=-abs(r['profit']);r['reported_eps']=-abs(r['reported_eps'])
            elif case=='future':quote['date']='2026-10-17'
            elif case=='stale':quote['date']='2026-10-01'
            else:value['inputs'][1]['available_on']='2026-10-16'
            self.assertIsNone(calculate(value,quote,self.today)['per'],case)
    def test_leap_year_weights_are_actual_days(self):
        rows=[]
        for start,end,profit in [('2023-01-01','2023-12-31',1000),('2024-01-01','2024-06-30',1200),('2023-01-01','2023-06-30',400)]:
            rows.append({'period_start':start,'period_end':end,'profit':profit,'weighted_shares':100,'reported_eps':profit/100,'basis':'CFS','definition':'ordinary_basic','currency':'KRW','source':'https://example.com/filing','available_on':'2024-08-01','document_sha256':'same'})
        result=calculate({'version':1,'status':'success','inputs':rows},{'close':100,'date':'2024-08-03','source':'test'},date(2024,8,4))
        self.assertEqual(result['weighted_shares'],100);self.assertEqual(result['eps'],18)
    def test_parser_rejects_wrong_company_year_unit_columns_and_diluted_substitution(self):
        original=pages(2026,2)
        for case in ('company','year','unit','columns','definition'):
            value=deepcopy(original)
            if case=='company':value[0]=value[0].replace('SAMSUNG','OTHER')
            elif case=='year':value[0]=value[0].replace('June 30, 2026','June 30, 2025')
            elif case=='unit':value[4]=value[4].replace('millions of Korean won','US dollars')
            elif case=='columns':value[4]=value[4].replace('6 Months','9 Months')
            else:value[4]=value[4].replace('(A) Ordinary shares','(B) Preference shares')
            with self.assertRaises(TtmError):parse_samsung(value,2026,2,ROOT+'2026_con_quarter02_all.pdf','hash',self.today)
    def test_listing_uses_only_live_pdf_anchors_and_latest_completed_link(self):
        html=f'<a href="{ROOT}2026_con_quarter02_all.pdf">reviewed</a><a>3rd quarter</a><script>"{ROOT}2026_con_quarter03_all.pdf"</script><a href="{ROOT}2025_con_quarter04_all.pdf">annual</a>'
        self.assertEqual(parse_listing(html),{(2026,2),(2025,4)})
        downloader=Mock(side_effect=lambda u:u.encode())
        extractor=lambda body:pages(2026,2) if b'2026_con' in body else pages(2025,4)
        saved=collect_samsung(self.today,download=downloader,extract=extractor,listed=parse_listing(html))
        self.assertEqual(len(saved['inputs']),3);self.assertEqual(downloader.call_count,2)
        self.assertIsNotNone(calculate(saved,self.quote,self.today)['per'])
    def test_newer_report_access_or_parse_failure_does_not_fall_back_to_old(self):
        download=Mock(side_effect=TtmError('403'))
        with self.assertRaises(TtmError):collect_samsung(self.today,download=download,listed={(2026,3),(2026,2),(2025,4)})
        download.assert_called_once()
    def test_cache_intervals_and_failed_refresh_flag(self):
        self.assertFalse(due(self.block,'2026-10-16T20:00:00+09:00'))
        self.assertTrue(due(self.block,'2026-10-17T01:00:00+09:00'))
        self.block['last_error']='timeout'
        self.assertTrue(due(self.block,'2026-10-16T19:15:00+09:00'))
        value=calculate(self.block,self.quote,self.today)
        self.assertIsNotNone(value['per']);self.assertTrue(any('이전 성공' in s for s in value['data_gaps']))
    def test_saved_snapshots_restore_ttm_and_fresh_financial_fetch_preserves_it(self):
        fixture=store_tests.FinancialStoreTests();fixture.setUp()
        value=deepcopy(fixture.saved);value['ttm']=self.block
        persist(fixture.client,'005930',value)
        restored=select_snapshot(fixture.db['payload'],'005930')
        self.assertEqual(restored['ttm'],self.block)
        fresh=deepcopy(fixture.saved);fresh['data']['fetched_at']='2026-10-16T19:30:00+09:00'
        persist(fixture.client,'005930',fresh)
        self.assertEqual(select_snapshot(fixture.db['payload'],'005930')['ttm'],self.block)
        self.assertEqual(fixture.db['payload']['journal'],[{'note':'preserve'}])
    def test_ttm_refresh_failure_keeps_success_and_does_not_reset_fetched_time(self):
        st=MagicMock();st.session_state={'lynch_data_005930':{'data':{},'ttm':self.block}}
        ns=functions(['lynch_ttm_refresh'],dict(st=st,datetime=datetime,ZoneInfo=ZoneInfo,ttm_due=due,collect_ttm=Mock(side_effect=TtmError('timeout')),
            TtmError=TtmError,DataError=TtmError,lynch_save_remote=Mock()))
        self.assertTrue(ns['lynch_ttm_refresh']('005930',self.today,force=True))
        saved=st.session_state['lynch_data_005930']['ttm']
        self.assertEqual(saved['inputs'],self.block['inputs']);self.assertEqual(saved['fetched_at'],self.block['fetched_at'])
        self.assertEqual(saved['last_error'],'timeout')
        self.assertIsNone(ns['lynch_ttm_refresh']('005930',self.today))
    def test_primary_per_and_annual_peg_are_separate_in_result_and_export(self):
        fixture=store_tests.FinancialStoreTests();fixture.setUp()
        saved=deepcopy(fixture.saved);saved['ttm']=self.block;saved['quote']=self.quote
        raw={'per':31.99,'peg':9.86,'cagr':3.244}
        result=describe(saved,raw,self.today)
        self.assertAlmostEqual(result['per'],9.318557971473673)
        self.assertEqual(result['annual_per'],31.99);self.assertEqual(result['annual_peg'],9.86)
        self.assertEqual(result['primary_per_type'],'ttm');self.assertEqual(result['valuation_basis']['peg_label'],'연간 PER 기준 과거 PEG')
        other=deepcopy(saved);other['data']['code']='000660'
        self.assertIsNone(describe(other,raw,self.today)['per'])
    def test_generic_dart_does_not_substitute_owner_profit_for_ordinary_profit(self):
        provider=Mock();provider.corp.return_value='00164779'
        def dart(endpoint,**kw):
            if endpoint=='company.json':return {'acc_mt':'12'}
            y=kw['bsns_year'];report=kw['reprt_code']
            return {'list':[{'account_nm':'지배기업의 소유주에게 귀속되는 당기순이익(손실)','sj_div':'IS','currency':'KRW','thstrm_add_amount':'1000','bsns_year':y,'reprt_code':report,'rcept_no':'20260814000001'}]}
        provider.dart.side_effect=dart
        with self.assertRaises(TtmError):collect_dart(provider,'000660',self.today)
    def test_real_pdf_text_extraction_roundtrip(self):
        import io
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
        writer=PdfWriter()
        for text in pages(2026,2):
            page=writer.add_blank_page(width=1000,height=1000)
            font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
            page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
            lines=['BT /F1 10 Tf 12 TL 20 950 Td']
            for line in text.splitlines():lines.append('('+line.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')+') Tj T*')
            lines.append('ET');stream=DecodedStreamObject();stream.set_data('\n'.join(lines).encode())
            page[NameObject('/Contents')]=writer._add_object(stream)
        buf=io.BytesIO();writer.write(buf)
        extracted=pdf_text(buf.getvalue())
        parsed=parse_samsung(extracted,2026,2,ROOT+'2026_con_quarter02_all.pdf','hash',self.today)
        self.assertEqual(parsed[0]['profit'],103966168*1e6)

    def test_bad_cached_ttm_and_overflow_do_not_crash_or_export_nonfinite_numbers(self):
        for value in (None,'bad',{'version':1,'status':'success','inputs':{'a':1,'b':2,'c':3}}):
            result=calculate(value,self.quote,self.today)
            self.assertIsNone(result['per']);json.dumps(result,allow_nan=False)
        value=deepcopy(self.block)
        for r in value['inputs']:
            r['weighted_shares']=1e308;r['profit']=1e308;r['reported_eps']=1
        result=calculate(value,self.quote,self.today)
        self.assertIsNone(result['per']);json.dumps(result,allow_nan=False)
    def test_zero_profit_keeps_eps_fact_and_no_per(self):
        for r in self.block['inputs']:r['profit']=0;r['reported_eps']=0
        result=calculate(self.block,self.quote,self.today)
        self.assertEqual(result['eps'],0);self.assertIsNone(result['per'])
    def test_newer_cloud_ttm_is_not_replaced_by_an_old_browser(self):
        fixture=store_tests.FinancialStoreTests();fixture.setUp()
        newer=deepcopy(fixture.saved);newer['ttm']={**self.block,'last_attempt_at':'2026-10-16T20:00:00+09:00'}
        persist(fixture.client,'005930',newer)
        stale=deepcopy(fixture.saved);stale['ttm']=self.block
        persist(fixture.client,'005930',stale)
        self.assertEqual(select_snapshot(fixture.db['payload'],'005930')['ttm']['last_attempt_at'],'2026-10-16T20:00:00+09:00')
    def test_primary_ttm_label_and_export_keep_annual_valuation_separate(self):
        from tests_valuation_evidence import ValuationEvidenceTests
        from predash.lynch_kis import calculate_reference
        from predash.lynch_view import metrics,table,number
        from predash.lynch import BS,SOURCE
        from predash.financial_freshness import fingerprint
        fixture=ValuationEvidenceTests();fixture.setUp();saved=fixture.saved;saved['ttm']=self.block
        st=MagicMock();st.session_state={}
        ns=functions(['lynch_results','lynch_options'],dict(st=st,json=json,describe_lynch_valuation=describe,calculate_kis_reference=calculate_reference,
            lynch_metrics=metrics,lynch_table=table,lynch_number=number,financial_fingerprint=fingerprint,LYNCH_BS=BS,LYNCH_SOURCE=SOURCE))
        ns['lynch_results'](saved,self.today)
        self.assertTrue(any('최근 12개월 PER' in str(c) and '9.32배' in str(c) for c in st.html.call_args_list))
        exported=json.loads(st.download_button.call_args.args[1])
        self.assertEqual(exported['schema_version'],2)
        self.assertAlmostEqual(exported['analysis']['per'],9.318557971473673)
        self.assertAlmostEqual(exported['analysis']['annual_per'],31.992687385740403)
        self.assertEqual(exported['analysis']['valuation_basis']['per_type'],'ttm')
        self.assertEqual(exported['analysis']['valuation_basis']['annual_per_type'],'annual_eps')
        self.assertEqual(exported['financial']['rows'][-1]['value'],6564)
