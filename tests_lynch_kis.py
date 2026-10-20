import unittest,json,ast,os,re
from pathlib import Path
from copy import deepcopy
from datetime import date,datetime
from zoneinfo import ZoneInfo
from unittest.mock import Mock,MagicMock
from predash.kis_probe import PRICE,RATIOS
from predash.kis import BrokerError
from predash.official import DataError
from predash.lynch_kis import build_reference,calculate_reference,collect_reference

class KisReferenceTests(unittest.TestCase):
    def fixture(self):
        return {'mode':'demo','code':'005930','fetched_at':'2026-10-15T15:00:00+09:00',
                'results':[{'path':PRICE,'success':True,'values':{'stck_prpr':210000,'eps':6564,'per':31.99,'stac_month':12}},
                           {'path':RATIOS,'success':True,'annual_eps':[{'period':str(y)+'12','eps':v} for y,v in zip(range(2021,2026),[5777,8057,2131,4950,6564])]+[{'period':'202606','eps':17687}], 'more_pages':False}]}
    def test_completed_years_only_and_reference_calculations(self):
        saved=build_reference(self.fixture(),date(2026,10,15))
        r=calculate_reference(saved,date(2026,10,15))
        self.assertEqual([x['year'] for x in r['history']],[2021,2022,2023,2024,2025])
        self.assertIn('202606',saved['excluded_periods'])
        self.assertAlmostEqual(r['cagr'],((6564/5777)**.25-1)*100)
        self.assertAlmostEqual(r['per'],210000/6564)
        self.assertEqual(r['validation_level'],'provider_reference_only')
        self.assertTrue(all(x['metric']=='KIS EPS' for x in saved['data']['rows']))
    def test_missing_month_or_extra_pages_blocks_cagr(self):
        for field in ('month','pages'):
            probe=self.fixture()
            if field=='month':probe['results'][0]['values'].pop('stac_month')
            else:probe['results'][1]['more_pages']=True
            saved=build_reference(probe,date(2026,10,15))
            self.assertIsNone(calculate_reference(saved,date(2026,10,15))['cagr'])
    def test_missing_eps_and_negative_growth_do_not_produce_peg(self):
        probe=self.fixture();probe['results'][1]['annual_eps'][2]['eps']=None
        self.assertIsNone(calculate_reference(build_reference(probe,date(2026,10,15)),date(2026,10,15))['peg'])
    def test_prior_day_close_selected_not_unfinished_current_candle(self):
        client=Mock();client.price_history.return_value=[{'basDt':'20261015','clpr':'999999'},{'basDt':'20261014','clpr':'200000'}]
        import predash.lynch_kis as mod
        from unittest.mock import patch
        with patch.object(mod,'run_probe',return_value=self.fixture()):
            saved=collect_reference(client,'005930',date(2026,10,15),pause=Mock())
        self.assertEqual(saved['quote']['date'],'2026-10-14');self.assertEqual(saved['quote']['close'],200000)
        self.assertEqual(saved['quote']['kind'],'종가')
    def test_close_failure_keeps_explicit_current_price(self):
        client=Mock();client.price_history.side_effect=BrokerError('종가 미확인')
        import predash.lynch_kis as mod
        from unittest.mock import patch
        with patch.object(mod,'run_probe',return_value=self.fixture()):
            saved=collect_reference(client,'005930',date(2026,10,15),pause=Mock())
        self.assertEqual(saved['quote']['kind'],'현재가');self.assertIn('closing_gap',saved['quote'])
    def test_real_page_dart_failure_falls_back_and_direct_path_skips_dart(self):
        for direct in (False,True):
            st=MagicMock();st.session_state={'watch_codes':['005930'],'watch_names':{},'lynch_kis_direct':direct};st.columns.return_value=[MagicMock(),MagicMock()];st.query_params={}
            st.selectbox.return_value='005930';st.checkbox.return_value=direct;st.button.side_effect=[True,False]
            saved=build_reference(self.fixture(),datetime.now(ZoneInfo('Asia/Seoul')).date())
            dart=Mock(side_effect=DataError('기업개황 timeout'));fallback=Mock(return_value=saved);render=Mock()
            ns=dict(lynch_refresh_price=lambda saved,today:saved,lynch_ttm_refresh=Mock(return_value=False),LYNCH_PAGE_STYLE='',lynch_status=Mock(),lynch_freshness_panel=Mock(),check_financial_snapshot=Mock(),lynch_restore_saved=Mock(),lynch_save_remote=Mock(),st=st,clean_codes=lambda codes:[c for c in codes if c],datetime=datetime,ZoneInfo=ZoneInfo,
                    api_key=lambda k:'configured',collect_lynch=dart,official_client=Mock(),
                    collect_kis_reference=fallback,kis_reference_client=Mock(),kis_lynch_result=render,
                    DataError=DataError,BrokerError=BrokerError,re=re)
            node=next(n for n in ast.parse(Path('app.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='lynch_page')
            exec(compile(ast.Module(body=[node],type_ignores=[]),'app.py','exec'),ns)
            ns['lynch_page']()
            self.assertEqual(dart.call_count,0 if direct else 1)
            fallback.assert_called_once();render.assert_called_once()
            self.assertEqual(st.session_state['lynch_data_005930']['source'],'KIS')
