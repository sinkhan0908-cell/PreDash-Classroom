import unittest,json
from copy import deepcopy
from datetime import date
from unittest.mock import Mock,patch
from predash.valuation_inputs import apply_annual,official_annual
from predash.valuation_evidence import describe
from predash.lynch_kis import calculate_reference
from predash.lynch_price import collect,latest
from predash.official import DataError
from predash.ttm import TtmError,parse_samsung,collect_samsung,ROOT
from tests_ttm import block,pages
import tests_valuation_evidence as evidence_tests
from predash.financial_store import persist,select_snapshot
import tests_financial_store as store_tests

class AppliedAnnualTests(unittest.TestCase):
    def setUp(self):
        fixture=evidence_tests.ValuationEvidenceTests();fixture.setUp()
        self.saved=fixture.saved;self.saved['ttm']=block();self.today=date(2026,10,19)
        self.saved['quote'].update(date='2026-10-16',close=215500)
    def result(self):return describe(self.saved,calculate_reference(self.saved,self.today),self.today)
    def test_partial_official_recomputes_annual_per_but_does_not_mix_kis_into_growth(self):
        before=deepcopy(self.saved);r=self.result()
        self.assertEqual(r['valuation_basis']['annual_eps_value'],6605)
        self.assertAlmostEqual(r['annual_per'],215500/6605)
        self.assertIsNone(r['cagr']);self.assertIsNone(r['annual_peg'])
        self.assertEqual(r['history'][-1]['provider_value'],6564)
        self.assertIsNone(r['history'][0]['value']);self.assertEqual(self.saved,before)
        self.assertAlmostEqual(r['ttm']['per'],9.562615442155126)
    def test_full_official_series_recomputes_growth_and_peg_together(self):
        rows=[]
        for year,eps in zip(range(2021,2026),(5777,8057,2131,4950,6605)):
            row=deepcopy(self.saved['ttm']['inputs'][0]);row.update(period_start=f'{year}-01-01',period_end=f'{year}-12-31',reported_eps=eps,profit=eps*row['weighted_shares'])
            rows.append(row)
        self.saved['ttm']['annual_eps']=rows
        r=self.result();expected=((6605/5777)**.25-1)*100
        self.assertAlmostEqual(r['cagr'],expected);self.assertAlmostEqual(r['annual_peg'],(215500/6605)/expected)
        self.assertEqual([r['value'] for r in r['history']],[5777,8057,2131,4950,6605])
    def test_wrong_code_bad_identity_split_and_future_reports_never_override(self):
        for field,value in [('code','000660'),('profit',1),('share_adjustment_flag',True),('available_on','2027-01-01')]:
            saved=deepcopy(self.saved)
            if field=='code':saved['ttm'][field]=value
            else:saved['ttm']['inputs'][0][field]=value
            self.assertEqual(official_annual(saved,self.today),{})
    def test_adjacent_restatement_conflict_blocks_cagr(self):
        self.saved['ttm']['annual_comparability_gaps']=['EPS 재작성 불일치']
        r=self.result();self.assertIsNone(r['cagr']);self.assertIn('EPS 재작성 불일치',r['growth_gaps'])
    def test_save_restore_preserves_applied_source_and_price_crosscheck(self):
        f=store_tests.FinancialStoreTests();f.setUp()
        self.saved['quote']['crosscheck']={'status':'matched'}
        persist(f.client,'005930',self.saved)
        restored=select_snapshot(f.db['payload'],'005930')
        r=describe(restored,calculate_reference(restored,self.today),self.today)
        self.assertAlmostEqual(r['annual_per'],215500/6605)
        self.assertEqual(restored['data']['rows'][-1]['value'],6564)
        self.assertEqual(restored['quote']['crosscheck']['status'],'matched')
    def test_legacy_annual_note_layout_is_distinct_from_preference_and_diluted(self):
        source=pages(2023,4)
        source[4]='''26. Earnings per Share
(A) Basic earnings per share
Basic earnings per share for the years ended December 31, 2023 and 2022 are calculated as follows:
(1) Ordinary shares
(In millions of Korean won, thousands of number of shares) 2023 2022
Profit for the year available for ordinary shares 12,719,321 48,099,117
Weighted-average number of ordinary shares outstanding 5,969,783 5,969,783
Basic earnings per ordinary share (in Korean won) 2,131 8,057
(2) Preference shares
Basic earnings per preference share (in Korean won) 2,132 8,058
(B) Diluted earnings per share'''
        r=parse_samsung(source,2023,4,ROOT+'2023_con_quarter04_all.pdf','hash',self.today)
        self.assertEqual([v['reported_eps'] for v in r],[2131,8057])
        with self.assertRaises(TtmError):parse_samsung([p.replace('Ordinary shares','Preference shares') for p in source],2023,4,ROOT+'2023_con_quarter04_all.pdf','hash',self.today)

class PriceCrosscheckTests(unittest.TestCase):
    today=date(2026,10,19)
    def loader(self,price=215500,day='20261016'):
        return Mock(return_value=[{'srtnCd':'005930','basDt':day,'clpr':price}])
    def test_same_date_equal_prices_match_and_mismatch_prefers_public(self):
        for other,status in [(215500,'matched'),(210000,'mismatch')]:
            q=collect('005930',self.today,self.loader(),self.loader(other))
            self.assertEqual(q['crosscheck']['status'],status);self.assertEqual(q['close'],215500)
            self.assertEqual(q['source'],'공공데이터포털')
    def test_one_source_and_different_dates_never_claim_match(self):
        public=self.loader();q=collect('005930',self.today,public,None)
        self.assertEqual(q['crosscheck']['status'],'single_source')
        q=collect('005930',self.today,self.loader(day='20261015'),self.loader())
        self.assertEqual(q['crosscheck']['status'],'date_mismatch');self.assertEqual(q['date'],'2026-10-15')
    def test_public_failure_uses_explicit_unverified_kis_fallback(self):
        q=collect('005930',self.today,Mock(side_effect=DataError('timeout')),self.loader())
        self.assertEqual(q['source'],'KIS 모의 일별 시세');self.assertEqual(q['crosscheck']['status'],'single_source')
        self.assertIn('public',q['crosscheck']['errors'])
        with self.assertRaises(DataError):collect('005930',self.today,None,None)
    def test_wrong_stock_intraday_nonfinite_and_conflicting_closes_are_rejected(self):
        rows=[{'srtnCd':'000660','basDt':'20261016','clpr':100},
              {'srtnCd':'005930','basDt':'20261019','clpr':200},
              {'srtnCd':'005930','basDt':'20261016','clpr':'nan'}]
        with self.assertRaises(DataError):latest(rows,self.today,'005930')
        with self.assertRaises(DataError):latest(self.loader().return_value+self.loader(210000).return_value,self.today,'005930')

class AnnualCollectionTests(unittest.TestCase):
    def test_collection_uses_listed_annuals_and_flags_changed_comparatives(self):
        listing={(2026,2),(2025,4),(2024,4),(2023,4),(2022,4)}
        def extract(body):
            year,quarter=map(int,body.decode().split(':'))
            return pages(year,quarter)
        def download(url):
            import re
            y,q=re.search(r'(20\d{2})_con_quarter0([1-4])',url).groups()
            return f'{y}:{q}'.encode()
        b=collect_samsung(date(2026,10,19),download=download,extract=extract,listed=listing)
        self.assertEqual({r['period_end'][:4] for r in b['annual_eps']},{'2021','2022','2023','2024','2025'})
        # The fixture deliberately gives conflicting current/prior values across annual PDFs.
        self.assertTrue(b['annual_comparability_gaps'])
        self.assertEqual(b['annual_eps_errors'],[])
        self.assertTrue(all(r.get('fetched_at') for r in b['annual_eps']))
    def test_optional_historical_failure_keeps_latest_ttm_success(self):
        listing={(2026,2),(2025,4),(2024,4)}
        def download(url):
            if '2024_' in url:raise TtmError('timeout')
            return b'2026' if '2026_' in url else b'2025'
        b=collect_samsung(date(2026,10,19),download=download,
            extract=lambda body:pages(int(body),2 if body==b'2026' else 4),listed=listing)
        self.assertEqual(b['status'],'success');self.assertEqual(len(b['inputs']),3)
        self.assertTrue(b['annual_eps_errors'])
    def test_partial_refresh_preserves_previous_annual_input_and_timestamp(self):
        from unittest.mock import MagicMock
        from tests_lynch_ui import functions
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from predash.official import DataError
        old=block();row=deepcopy(old['inputs'][0])
        row.update(period_start='2021-01-01',period_end='2021-12-31',fetched_at='2026-10-16T19:00:00+09:00')
        old['annual_eps']=[row]
        new=block();new.update(annual_eps=[],annual_eps_errors=['2022년: timeout'])
        st=MagicMock();st.session_state={'lynch_data_005930':{'data':{'code':'005930'},'ttm':old}}
        ns=functions(['lynch_ttm_refresh'],dict(st=st,datetime=datetime,ZoneInfo=ZoneInfo,collect_ttm=Mock(return_value=new),
            lynch_save_remote=Mock(),TtmError=TtmError,DataError=DataError))
        ns['lynch_ttm_refresh']('005930',date(2026,10,19),force=True)
        retained=st.session_state['lynch_data_005930']['ttm']['annual_eps'][0]
        self.assertEqual(retained,row)
