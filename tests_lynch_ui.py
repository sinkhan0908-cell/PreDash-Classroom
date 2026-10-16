import ast,sys,types,json,re,unittest
try:import requests
except ImportError:sys.modules['requests']=types.SimpleNamespace(RequestException=Exception,request=None)
from pathlib import Path
from copy import deepcopy
from datetime import datetime,date
from zoneinfo import ZoneInfo
from unittest.mock import Mock,MagicMock
from predash.kis import BrokerError
from predash.official import DataError
from predash.cloud_store import StorageError
from predash.lynch_view import metrics,table,status,number,PAGE_STYLE
from predash.lynch import analyse,BS,SOURCE
from predash.financial_freshness import fingerprint
from tests_strategy_evidence import fixture


def functions(names,ns):
    nodes=[n for n in ast.parse(Path('app.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name in names]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'app.py','exec'),ns)
    return ns


class CompactLynchTests(unittest.TestCase):
    def setUp(self):
        self.saved={'data':fixture(),'quote':{'close':1600,'date':'2026-10-15','source':'KIS','kind':'종가'}}
        self.saved['data'].update(name='예시기업',fetched_at='2026-10-15T12:00:00+09:00')
        self.st=MagicMock();self.st.session_state={'lynch_data_005930':deepcopy(self.saved),'watch_codes':['005930'],'watch_names':{}}
    def updater(self):
        return functions(['lynch_update_saved'],dict(st=self.st,lynch_freshness_panel=Mock(),lynch_refresh_price=Mock(),lynch_save_remote=Mock(),BrokerError=BrokerError,DataError=DataError))
    def test_single_action_checks_financials_and_refreshes_price_without_full_collection(self):
        ns=self.updater();ns['lynch_refresh_price'].return_value={**self.saved,'quote':{'close':1700,'date':'2026-10-16'}}
        ns['lynch_update_saved']('005930',date(2026,10,16))
        ns['lynch_freshness_panel'].assert_called_once_with('005930',self.saved,date(2026,10,16),manual=True,automatic=False,rerun=False)
        ns['lynch_refresh_price'].assert_called_once()
        self.assertEqual(self.st.session_state['lynch_data_005930']['data'],self.saved['data'])
        self.assertEqual(self.st.session_state['lynch_data_005930']['quote']['close'],1700)
    def test_price_failure_keeps_new_financial_and_previous_price(self):
        ns=self.updater();new=deepcopy(self.saved);new['data']['fetched_at']='2026-10-16T12:00:00+09:00'
        ns['lynch_freshness_panel'].side_effect=lambda *a,**k:self.st.session_state.update(lynch_data_005930=new)
        ns['lynch_refresh_price'].side_effect=BrokerError('timeout')
        ns['lynch_update_saved']('005930',date(2026,10,16))
        self.assertEqual(self.st.session_state['lynch_data_005930'],new)
        self.assertEqual(self.st.session_state['lynch_data_005930']['quote']['date'],'2026-10-15')
        self.assertTrue(ns['lynch_save_remote'].call_args.kwargs['failed'])
    def test_financial_check_failure_still_refreshes_price(self):
        ns=self.updater()
        ns['lynch_freshness_panel'].side_effect=lambda *a,**k:self.st.session_state.update(lynch_freshness_005930_DART={'status':'failed'})
        ns['lynch_refresh_price'].return_value={**self.saved,'quote':{'close':1800,'date':'2026-10-16'}}
        ns['lynch_update_saved']('005930',date(2026,10,16))
        self.assertEqual(self.st.session_state['lynch_data_005930']['quote']['close'],1800)
        self.assertEqual(self.st.session_state['lynch_freshness_005930_DART']['status'],'failed')
    def test_page_has_one_action_uses_cache_and_does_not_check_twice(self):
        self.st.columns.return_value=[MagicMock(),MagicMock()];self.st.query_params={}
        self.st.selectbox.return_value='005930';self.st.button.return_value=True
        ns=functions(['lynch_page'],dict(st=self.st,LYNCH_PAGE_STYLE=PAGE_STYLE,clean_codes=lambda c:[x for x in c if x],datetime=datetime,ZoneInfo=ZoneInfo,
            lynch_restore_saved=Mock(),lynch_update_saved=Mock(),lynch_status=Mock(),lynch_results=Mock(),lynch_freshness_panel=Mock()))
        ns['lynch_page']()
        self.st.button.assert_called_once();self.assertEqual(self.st.button.call_args.args[0],'최신 자료 확인')
        ns['lynch_update_saved'].assert_called_once();ns['lynch_freshness_panel'].assert_not_called();ns['lynch_results'].assert_called_once()
    def test_collapsed_evidence_and_settings_preserve_export_and_unknown_balances(self):
        ns=functions(['lynch_results','lynch_options'],dict(st=self.st,json=json,analyse_lynch=analyse,lynch_metrics=metrics,lynch_table=table,lynch_number=number,
            financial_fingerprint=fingerprint,LYNCH_BS=BS,LYNCH_SOURCE=SOURCE))
        ns['lynch_results'](self.saved,date(2026,10,16))
        self.assertEqual([c.args[0] for c in self.st.expander.call_args_list],['분석 근거 보기','고급 설정'])
        self.assertTrue(all(c.kwargs['expanded'] is False for c in self.st.expander.call_args_list))
        export=json.loads(self.st.download_button.call_args.args[1]);self.assertEqual(export['financial'],self.saved['data'])
        self.assertTrue(any('현금·차입금 미확인' in str(c) for c in self.st.info.call_args_list))
    def test_html_escapes_external_text_and_unknown_is_not_zero(self):
        rendered=table(['항목'],[['<script>alert(1)</script>']])
        self.assertNotIn('<script>',rendered);self.assertIn('&lt;script&gt;',rendered)
        self.assertEqual(number(None),'미확인');self.assertEqual(number(0),'0.0')
    def test_status_keeps_current_price_label_and_failure(self):
        self.saved['source']='KIS';self.saved['quote']['kind']='현재가'
        rendered=status(self.saved,{'status':'failed','checked_at':'2026-10-16T12:00:00+09:00'})
        self.assertIn('확인 실패',rendered);self.assertIn('현재가 10.15',rendered);self.assertIn('원문 미대조',rendered)
        self.assertNotIn('종가 10.15',rendered)
