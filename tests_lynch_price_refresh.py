import unittest
from copy import deepcopy
from datetime import date,datetime
from zoneinfo import ZoneInfo
from unittest.mock import Mock,MagicMock
from predash import financial_validation
from predash.official import DataError
from predash.kis import BrokerError
from predash.lynch_price import collect
from predash.ttm import calculate
from tests_lynch_ui import functions
import tests_pc_dashboard as pc_fixtures
from tests_ttm import block


class PriceOnlyRefreshTests(unittest.TestCase):
    def setup_ui(self):
        fixture=pc_fixtures.PcDashboardTests();saved=fixture.saved();saved['data']['code']='005930'
        saved['quote']={'close':210000,'date':'2026-10-19','source':'fixture'}
        saved['ttm']=block()
        st=MagicMock();st.session_state={'lynch_data_005930':deepcopy(saved)}
        updater=Mock(return_value={**deepcopy(saved),'quote':{'close':230000,'date':'2026-10-20','source':'fixture'}})
        store=Mock()
        ns=functions(['lynch_update_price_only'],dict(st=st,financial_validation_module=financial_validation,
             lynch_refresh_price=updater,lynch_save_remote=store,DataError=DataError,BrokerError=BrokerError))
        return saved,st,updater,store,ns

    def test_price_change_keeps_financial_inputs_and_recalculates_ttm_per(self):
        saved,st,updater,store,ns=self.setup_ui()
        ns['lynch_update_price_only']('005930',date(2026,10,20))
        refreshed=st.session_state['lynch_data_005930']
        self.assertEqual(refreshed['data'],saved['data'])
        self.assertEqual(refreshed['ttm'],saved['ttm'])
        result=calculate(refreshed['ttm'],refreshed['quote'],date(2026,10,20))
        self.assertAlmostEqual(result['per'],230000/result['eps'])
        self.assertEqual(store.call_args.kwargs,{'kind':'price'})

    def test_failed_older_and_stale_prices_keep_previous_price_and_financials(self):
        for problem in ('network','older','stale'):
            saved,st,updater,store,ns=self.setup_ui()
            if problem=='network':updater.side_effect=DataError('timeout')
            else:updater.return_value['quote']['date']='2026-10-18' if problem=='older' else '2026-10-01'
            ns['lynch_update_price_only']('005930',date(2026,10,20))
            self.assertEqual(st.session_state['lynch_data_005930'],saved)
            self.assertTrue(store.call_args.kwargs['failed'])
            self.assertIn('lynch_data_005930_price_error',st.session_state)

    def test_price_button_skips_all_financial_and_ttm_collection(self):
        saved,st,updater,store,ns=self.setup_ui()
        st.session_state.update(watch_codes=['005930'],watch_names={})
        st.selectbox.return_value='005930';st.columns.return_value=[MagicMock(),MagicMock()]
        st.button.side_effect=[False,True]
        runner=functions(['lynch_page'],dict(st=st,datetime=datetime,ZoneInfo=ZoneInfo,StorageError=RuntimeError,
            clean_codes=lambda x:x,LYNCH_PAGE_STYLE='',lynch_restore_saved=Mock(),lynch_update_price_only=Mock(),
            lynch_status=Mock(),kis_lynch_result=Mock(),lynch_results=Mock(),lynch_freshness_panel=Mock(),
            lynch_ttm_refresh=Mock(),lynch_update_saved=Mock()))
        runner['lynch_page']()
        runner['lynch_update_price_only'].assert_called_once()
        runner['lynch_update_saved'].assert_not_called()
        runner['lynch_freshness_panel'].assert_not_called()
        runner['lynch_ttm_refresh'].assert_not_called()


class LatestClosingPriceTests(unittest.TestCase):
    def loader(self,day,close):
        return Mock(return_value=[{'srtnCd':'214450','basDt':day,'clpr':close}])

    def test_after_cutoff_uses_current_daily_close_from_newer_provider(self):
        q=collect('214450',date(2026,10,20),self.loader('20261019',277500),self.loader('20261020',280000),
                  at=datetime(2026,10,20,17,45,tzinfo=ZoneInfo('Asia/Seoul')))
        self.assertEqual((q['date'],q['close']),('2026-10-20',280000))
        self.assertEqual(q['crosscheck']['status'],'date_mismatch')
        self.assertEqual(q['crosscheck']['selected'],'kis')

    def test_before_cutoff_excludes_intraday_row_and_keeps_prior_close(self):
        kis=Mock(return_value=[{'srtnCd':'214450','basDt':'20261020','clpr':280000},
                               {'srtnCd':'214450','basDt':'20261019','clpr':277500}])
        q=collect('214450',date(2026,10,20),self.loader('20261019',277500),kis,
                  at=datetime(2026,10,20,15,0,tzinfo=ZoneInfo('Asia/Seoul')))
        self.assertEqual(q['date'],'2026-10-19')
        self.assertEqual(q['crosscheck']['status'],'matched')

    def test_same_date_keeps_public_priority_and_flags_mismatch(self):
        q=collect('214450',date(2026,10,20),self.loader('20261020',280000),self.loader('20261020',281000),
                  at=datetime(2026,10,20,17,45,tzinfo=ZoneInfo('Asia/Seoul')))
        self.assertEqual(q['close'],280000)
        self.assertEqual(q['crosscheck']['status'],'mismatch')
