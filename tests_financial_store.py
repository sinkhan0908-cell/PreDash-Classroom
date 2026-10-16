import unittest,json,ast,types,sys
from copy import deepcopy
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import Mock,MagicMock
try:import requests
except ImportError:sys.modules['requests']=types.SimpleNamespace(RequestException=Exception,request=None)
from predash.financial_store import persist,select_snapshot,clean_snapshot,FIELD
from predash.cloud_store import StorageError
from tests_strategy_evidence import fixture
from predash.kis import BrokerError
from predash.official import DataError

class FinancialStoreTests(unittest.TestCase):
    def setUp(self):
        data=fixture();data.update(name='공개기업',fetched_at='2026-10-12T10:00:00+09:00')
        self.saved={'data':data,'quote':{'close':1600,'date':'2026-10-12','source':'KIS','fetched_at':'2026-10-12T10:00:00+09:00'}}
        self.db={'id':'personal','version':1,'payload':{'stocks':[{'code':'005930','name':'삼성전자'}],'journal':[{'note':'preserve'}],'runs':[1]}}
        self.client=Mock();self.client.load.side_effect=lambda:deepcopy(self.db)
        def request(method,**kw):
            self.assertEqual(method,'PATCH');self.assertEqual(kw['params']['version'],'eq.'+str(self.db['version']))
            self.db.update(deepcopy(kw['json']));return [deepcopy(self.db)]
        self.client.request.side_effect=request
    def test_store_restore_preserves_inputs_dates_other_payload_and_recalculates(self):
        persist(self.client,'005930',self.saved)
        restored=select_snapshot(self.db['payload'],'005930')
        self.assertEqual(restored['data']['fetched_at'],self.saved['data']['fetched_at'])
        self.assertEqual(restored['quote']['date'],'2026-10-12')
        self.assertEqual(self.db['payload']['journal'],[{'note':'preserve'}])
        self.assertEqual(self.db['payload']['runs'],[1])
        self.assertTrue(restored['_storage']['restored'])
        self.assertNotIn('analysis',restored)
    def test_sources_separate_failure_preserves_success_and_is_restored(self):
        persist(self.client,'005930',self.saved)
        other=deepcopy(self.saved);other['source']='KIS';other['data']['fetched_at']='2026-10-13T10:00:00+09:00'
        persist(self.client,'005930',other)
        persist(self.client,'005930',failed=True)
        entry=self.db['payload'][FIELD]['items']['005930']
        self.assertIn('DART',entry);self.assertIn('KIS',entry)
        restored=select_snapshot(self.db['payload'],'005930')
        self.assertEqual(restored['source'],'KIS')
        self.assertEqual(restored['_storage']['last_attempt']['status'],'failed')
    def test_incomplete_or_secret_inputs_never_overwrite_saved_success(self):
        persist(self.client,'005930',self.saved);previous=deepcopy(self.db)
        for bad in ('missing','secret'):
            value=deepcopy(self.saved)
            if bad=='missing':next(r for r in value['data']['rows'] if r['metric']=='기본 EPS')['value']=None
            else:value['data']['appsecret']='DO_NOT_STORE'
            with self.assertRaises(StorageError):persist(self.client,'005930',value)
            self.assertEqual(self.db,previous)
    def test_failed_quote_keeps_old_price_original_date_and_marks_reason(self):
        persist(self.client,'005930',self.saved)
        newer=deepcopy(self.saved);newer['data']['fetched_at']='2026-10-13T10:00:00+09:00';newer['quote']={'error':'timeout'}
        persist(self.client,'005930',newer)
        restored=select_snapshot(self.db['payload'],'005930')
        self.assertEqual(restored['quote']['date'],'2026-10-12');self.assertIn('refresh_error',restored['quote'])
    def test_cas_race_reloads_merges_and_preserves_other_changes(self):
        original=self.client.request.side_effect
        def race(method,**kw):
            self.client.request.side_effect=original
            self.db['payload']['journal'].append({'note':'other device'});self.db['version']+=1
            return []
        self.client.request.side_effect=race
        persist(self.client,'005930',self.saved)
        self.assertEqual(self.client.request.call_count,2)
        self.assertEqual(len(self.db['payload']['journal']),2)
    def test_newer_snapshot_not_overwritten_and_bad_version_not_loaded(self):
        persist(self.client,'005930',self.saved)
        old=deepcopy(self.saved);old['data']['fetched_at']='2026-10-11T10:00:00+09:00'
        with self.assertRaises(StorageError):persist(self.client,'005930',old)
        self.db['payload'][FIELD]['version']=999
        self.assertIsNone(select_snapshot(self.db['payload'],'005930'))
    def test_page_failed_requery_still_renders_old_snapshot_over_24_hours(self):
        st=MagicMock();cached=deepcopy(self.saved);cached['source']='KIS'
        st.session_state={'watch_codes':['005930'],'watch_names':{},'lynch_data_005930':cached,'lynch_force_full':True,'lynch_kis_direct':True}
        st.columns.return_value=[MagicMock(),MagicMock()];st.query_params={};st.selectbox.return_value='005930';st.checkbox.return_value=True
        st.button.side_effect=[True,False]
        render=Mock();store=Mock()
        ns=dict(LYNCH_PAGE_STYLE='',lynch_status=Mock(),lynch_freshness_panel=Mock(),st=st,datetime=datetime,ZoneInfo=ZoneInfo,clean_codes=lambda x:[c for c in x if c],lynch_restore_saved=Mock(),
                collect_kis_reference=Mock(side_effect=BrokerError('timeout')),kis_reference_client=Mock(),lynch_save_remote=store,
                DataError=DataError,BrokerError=BrokerError,kis_lynch_result=render)
        node=next(n for n in ast.parse(Path('app.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='lynch_page')
        exec(compile(ast.Module(body=[node],type_ignores=[]),'app.py','exec'),ns)
        ns['lynch_page']()
        render.assert_called_once();self.assertEqual(st.session_state['lynch_data_005930'],cached)
        self.assertTrue(store.call_args.kwargs['failed'])
        self.assertTrue(any('최신 여부 확인 실패' in str(c) for c in st.warning.call_args_list))
    def test_new_session_restore_uses_cloud_without_external_queries(self):
        persist(self.client,'005930',self.saved)
        st=MagicMock();st.session_state={'_cloud_snapshot':self.db}
        ns={'st':st,'select_financial_snapshot':select_snapshot}
        node=next(n for n in ast.parse(Path('app.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='lynch_restore_saved')
        exec(compile(ast.Module(body=[node],type_ignores=[]),'app.py','exec'),ns)
        ns['lynch_restore_saved']('005930')
        self.assertEqual(st.session_state['lynch_data_005930']['data']['fetched_at'],self.saved['data']['fetched_at'])
    def test_price_refresh_reuses_financial_inputs_without_recollecting(self):
        import math,re
        ns={'datetime':datetime,'ZoneInfo':ZoneInfo,'math':math,'re':re,
            'quote_with_fallback':Mock(return_value=(1700,'20261014','public','공공데이터포털')),'official_client':Mock()}
        node=next(n for n in ast.parse(Path('app.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='lynch_refresh_price')
        exec(compile(ast.Module(body=[node],type_ignores=[]),'app.py','exec'),ns)
        result=ns['lynch_refresh_price'](self.saved,datetime(2026,10,15).date())
        self.assertEqual(result['data'],self.saved['data'])
        self.assertEqual(result['quote']['date'],'2026-10-14')
        self.assertEqual(self.saved['quote']['date'],'2026-10-12')
    def test_financial_save_does_not_mask_other_device_watchlist_conflict(self):
        st=MagicMock();old=deepcopy(self.db);st.session_state={'_cloud_snapshot':old}
        remote=deepcopy(self.db);remote['version']=2;remote['payload']['stocks']=[{'code':'000660','name':'SK하이닉스'}]
        ns={'st':st,'cloud_client':lambda:(self.client,'id'),'persist_financial_snapshot':Mock(return_value=remote),'StorageError':StorageError}
        node=next(n for n in ast.parse(Path('app.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='lynch_save_remote')
        exec(compile(ast.Module(body=[node],type_ignores=[]),'app.py','exec'),ns)
        ns['lynch_save_remote']('005930',self.saved)
        self.assertEqual(st.session_state['_cloud_snapshot'],old)
        self.assertIn('다른 기기',st.session_state['_cloud_error'])
