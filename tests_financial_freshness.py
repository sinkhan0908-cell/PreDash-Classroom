import unittest,sys,types
try:import requests
except ImportError:sys.modules['requests']=types.SimpleNamespace(RequestException=Exception,request=None)
from copy import deepcopy
from datetime import date
from unittest.mock import Mock,patch,MagicMock
import ast
from pathlib import Path
from predash.financial_freshness import fingerprint,due,check_dart,check_kis
from predash.financial_store import persist,select_snapshot,FIELD
from predash.cloud_store import StorageError
from predash.kis_probe import RATIOS,PRICE
import tests_financial_store as store_tests

class FreshnessTests(unittest.TestCase):
    def setUp(self):
        fixture=store_tests.FinancialStoreTests();fixture.setUp()
        self.saved=fixture.saved;self.client=fixture.client;self.db=fixture.db
        self.today=date(2026,10,15);self.at='2026-10-15T12:00:00+09:00'
    def record(self,status='unchanged'):
        return {'fingerprint':fingerprint(self.saved),'checked_at':self.at,'status':status}
    def filing(self,receipt='20261015000001',name='[기재정정]사업보고서 (2025.12)'):
        return {'corp_code':'00126380','stock_code':'005930','rcept_no':receipt,'rcept_dt':'20261015','report_nm':name}
    def provider(self,rows):
        return Mock(dart=Mock(return_value={'list':rows,'total_page':1,'total_count':len(rows)}))
    def test_interval_backoff_and_future_clock(self):
        self.assertFalse(due(self.saved,self.record(),'2026-10-15T17:59:59+09:00'))
        self.assertTrue(due(self.saved,self.record(),'2026-10-15T18:00:00+09:00'))
        self.assertFalse(due(self.saved,self.record('failed'),'2026-10-15T12:14:59+09:00'))
        self.assertTrue(due(self.saved,self.record('failed'),'2026-10-15T12:15:00+09:00'))
        self.assertTrue(due(self.saved,self.record(),'2026-10-15T11:00:00+09:00'))
    def test_fingerprint_ignores_price_and_separates_provider_and_new_data(self):
        other=deepcopy(self.saved);other['quote']['date']='2026-10-15'
        self.assertEqual(fingerprint(other),fingerprint(self.saved))
        other['source']='KIS';self.assertNotEqual(fingerprint(other),fingerprint(self.saved))
        self.assertTrue(due(other,self.record(),self.at))
    def test_dart_correction_and_new_regular_reports_detected(self):
        for name in ('[기재정정]사업보고서 (2025.12)','반기보고서 (2026.06)','분기보고서 (2026.09)'):
            provider=self.provider([self.filing(name=name)])
            self.assertTrue(check_dart(provider,self.saved,self.today))
            provider.corp.assert_not_called()
            self.assertEqual(provider.dart.call_args.kwargs['last_reprt_at'],'N')
    def test_dart_known_receipt_and_empty_are_unchanged(self):
        row=self.filing();self.saved['data']['rows'][0]['receipt']=row['rcept_no']
        self.assertFalse(check_dart(self.provider([row]),self.saved,self.today))
        self.assertFalse(check_dart(Mock(dart=Mock(return_value=None)),self.saved,self.today))
    def test_dart_malformed_wrong_company_and_missing_pages_are_unknown(self):
        for response in ({}, {'list':[],'total_page':2,'total_count':0},
                         {'list':[dict(self.filing(),stock_code='000660')],'total_page':1,'total_count':1},
                         {'list':[dict(self.filing(),rcept_no='bad')],'total_page':1,'total_count':1}):
            with self.assertRaises(StorageError):check_dart(Mock(dart=Mock(return_value=response)),self.saved,self.today)
    def probe(self):
        self.saved['source']='KIS'
        rows=[r for r in self.saved['data']['rows'] if r['metric']=='기본 EPS']
        for r in rows:r['metric']='KIS EPS';r['period_end']=f"{r['year']}-12-31"
        return {'code':'005930','fetched_at':self.at,'results':[
            {'path':PRICE,'success':True,'values':{'stac_month':12}},
            {'path':RATIOS,'success':True,'more_pages':False,'annual_eps':[{'period':str(r['year'])+'12','eps':r['value']} for r in rows]+[{'period':'202606','eps':99999}]}]}
    def test_kis_same_eps_and_interim_excluded_preserves_price(self):
        probe=self.probe()
        with patch('predash.financial_freshness.run_probe',return_value=probe):
            changed,candidate=check_kis(Mock(),self.saved,self.today)
        self.assertFalse(changed);self.assertEqual(candidate['quote'],self.saved['quote'])
        self.assertEqual(candidate['excluded_periods'],['202606'])
    def test_kis_eps_change_detected(self):
        probe=self.probe();probe['results'][1]['annual_eps'][0]['eps']+=1
        with patch('predash.financial_freshness.run_probe',return_value=probe):
            self.assertTrue(check_kis(Mock(),self.saved,self.today)[0])
    def test_kis_missing_eps_pages_and_month_are_unknown(self):
        for case in ('eps','pages','month'):
            self.setUp();probe=self.probe()
            if case=='eps':probe['results'][1]['annual_eps'][0]['eps']=None
            elif case=='pages':probe['results'][1]['more_pages']=True
            else:probe['results'][0]['values']['stac_month']=None
            with patch('predash.financial_freshness.run_probe',return_value=probe),self.assertRaises(StorageError):
                check_kis(Mock(),self.saved,self.today)
    def test_metadata_restore_keeps_original_data_timestamp_and_other_payload(self):
        persist(self.client,'005930',self.saved)
        persist(self.client,'005930',freshness=self.record(),checked_source='DART',attempt_kind='freshness')
        restored=select_snapshot(self.db['payload'],'005930')
        self.assertEqual(restored['_storage']['freshness'],self.record())
        self.assertEqual(restored['data']['fetched_at'],self.saved['data']['fetched_at'])
        self.assertEqual(self.db['payload']['journal'],[{'note':'preserve'}])
    def test_stale_metadata_cannot_attach_to_new_snapshot(self):
        newer=deepcopy(self.saved);newer['data']['fetched_at']=self.at
        persist(self.client,'005930',newer)
        before=deepcopy(self.db)
        with self.assertRaises(StorageError):persist(self.client,'005930',freshness=self.record(),checked_source='DART')
        self.assertEqual(self.db,before)
    def panel(self,check):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        st=MagicMock();st.session_state={'lynch_data_005930':deepcopy(self.saved)}
        st.checkbox.return_value=True;st.button.return_value=False
        ns=dict(st=st,datetime=datetime,ZoneInfo=ZoneInfo,financial_fingerprint=fingerprint,financial_check_due=due,
                check_dart_changes=check,official_client=Mock(),collect_lynch=Mock(side_effect=StorageError('incomplete')),
                check_financial_snapshot=Mock(),lynch_save_remote=Mock(),StorageError=StorageError,DataError=StorageError,BrokerError=StorageError)
        node=next(n for n in ast.parse(Path('app.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='lynch_freshness_panel')
        exec(compile(ast.Module(body=[node],type_ignores=[]),'app.py','exec'),ns)
        ns['lynch_freshness_panel']('005930',self.saved,self.today)
        return st,ns
    def test_refresh_failure_retains_previous_snapshot_and_backs_off(self):
        check=Mock(return_value=True);st,ns=self.panel(check)
        self.assertEqual(st.session_state['lynch_data_005930'],self.saved)
        self.assertEqual(st.session_state['lynch_freshness_005930_DART']['status'],'failed')
        ns['lynch_freshness_panel']('005930',self.saved,self.today)
        check.assert_called_once();st.rerun.assert_not_called()
    def test_no_change_does_not_recollect_and_repeated_render_does_not_recheck(self):
        check=Mock(return_value=False);st,ns=self.panel(check)
        ns['lynch_freshness_panel']('005930',self.saved,self.today)
        check.assert_called_once();ns['collect_lynch'].assert_not_called()
        self.assertIsNone(ns['lynch_save_remote'].call_args.args[1])
    def test_timeout_is_failed_not_unchanged(self):
        st,ns=self.panel(Mock(side_effect=StorageError('timeout')))
        self.assertEqual(st.session_state['lynch_freshness_005930_DART']['status'],'failed')

    def test_price_only_save_preserves_latest_check(self):
        persist(self.client,'005930',self.saved)
        persist(self.client,'005930',freshness=self.record(),checked_source='DART',attempt_kind='freshness')
        priced=deepcopy(self.saved);priced['quote']['close']=1900
        persist(self.client,'005930',priced,attempt_kind='price')
        self.assertEqual(select_snapshot(self.db['payload'],'005930')['_storage']['freshness'],self.record())

    def test_detected_change_validates_saves_and_updates_screen(self):
        st,ns=self.panel(Mock(return_value=False))
        st.session_state.pop('lynch_freshness_005930_DART')
        updated=deepcopy(self.saved);updated['data']['fetched_at']=self.at
        ns['check_dart_changes'].return_value=True
        ns['collect_lynch'].side_effect=None;ns['collect_lynch'].return_value=updated['data']
        from predash.financial_store import clean_snapshot
        ns['check_financial_snapshot']=clean_snapshot
        ns['lynch_freshness_panel']('005930',self.saved,self.today)
        self.assertEqual(st.session_state['lynch_data_005930']['data'],updated['data'])
        self.assertEqual(st.session_state['lynch_freshness_005930_DART']['status'],'updated')
        st.rerun.assert_called_once()
        self.assertEqual(ns['lynch_save_remote'].call_args.kwargs['checked_source'],'DART')
