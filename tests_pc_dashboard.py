import unittest
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import Mock,MagicMock
from predash.cloud_store import StorageError
from tests_lynch_ui import functions
from tests_strategy_evidence import fixture


class PcDashboardTests(unittest.TestCase):
    def saved(self):
        data=fixture();data.update(code='214450',fetched_at='2026-10-20T13:00:00+09:00')
        return {'data':data,'source':'KIS','quote':{'close':277500},'ttm':{'status':'success'}}

    def test_pc_load_uses_storage_only_and_replaces_stale_session(self):
        st=MagicMock();st.session_state={'lynch_data_214450':{'ttm':{'status':'failed'}},'lynch_data_214450_error':'old'}
        client=Mock();client.load.return_value={'payload':{'stocks':[]}}
        latest=self.saved()
        ns=functions(['lynch_load_pc_snapshot'],dict(st=st,cloud_client=Mock(return_value=(client,'id')),
            select_financial_snapshot=Mock(return_value=latest),StorageError=StorageError))
        ns['lynch_load_pc_snapshot']('214450')
        client.load.assert_called_once()
        self.assertEqual(st.session_state['lynch_data_214450'],latest)
        self.assertNotIn('lynch_data_214450_error',st.session_state)

    def test_pharma_page_never_starts_automatic_provider_queries(self):
        for pressed in (False,True):
            st=MagicMock();saved=self.saved()
            st.session_state={'watch_codes':['214450'],'watch_names':{},'lynch_data_214450':saved,'lynch_auto_214450':True}
            st.columns.return_value=[MagicMock(),MagicMock()];st.selectbox.return_value='214450';st.button.side_effect=[pressed,False]
            ns=functions(['lynch_page'],dict(st=st,datetime=datetime,ZoneInfo=ZoneInfo,StorageError=StorageError,
                clean_codes=lambda x:x,LYNCH_PAGE_STYLE='',lynch_restore_saved=Mock(),lynch_load_pc_snapshot=Mock(),
                lynch_status=Mock(),kis_lynch_result=Mock(),lynch_freshness_panel=Mock(),lynch_ttm_refresh=Mock(),lynch_update_saved=Mock()))
            ns['lynch_page']()
            ns['lynch_freshness_panel'].assert_not_called()
            ns['lynch_ttm_refresh'].assert_not_called()
            ns['lynch_update_saved'].assert_not_called()
            self.assertEqual(ns['lynch_load_pc_snapshot'].call_count,int(pressed))
            self.assertEqual(st.button.call_args_list[0].args[0],'PC 저장자료 불러오기')
