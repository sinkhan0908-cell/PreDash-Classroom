import unittest
from datetime import date,datetime,timedelta
from pathlib import Path
from unittest.mock import Mock,MagicMock
from zoneinfo import ZoneInfo
from predash.official import DataError
from predash.kis import BrokerError
from predash.cloud_store import StorageError
from predash.ttm import calculate
from predash.dart_xbrl import parse
from predash.decision import export_review
from tests_dart_xbrl_actual import zipped
from tests_lynch_ui import functions


def saved_financial():
    root=Path('tests_fixtures');today=date(2026,10,20)
    annual=parse(zipped((root/'pharma-20260319001417-eps.xbrl').read_bytes()),
                 [('2025-01-01','2025-12-31')],'20260319001417',today)
    interim=parse(zipped((root/'pharma-20260814002997-eps.xbrl').read_bytes()),
                  [('2026-01-01','2026-06-30'),('2025-01-01','2025-06-30')],'20260814002997',today)
    return {'code':'214450','name':'파마리서치','quote':{'close':264500,'date':'2026-10-20','source':'fixture'},
            'ttm':{'code':'214450','status':'success','version':1,'inputs':annual+interim,'fetched_at':'2026-10-20T13:00:00+09:00'}}


class PcResearchEvidenceTests(unittest.TestCase):
    def collect(self,saved):
        st=MagicMock();st.session_state={'watch_names':{'214450':'파마리서치'}}
        provider=Mock();progress=Mock()
        ns=functions(['watch_fetch'],dict(st=st,datetime=datetime,timedelta=timedelta,ZoneInfo=ZoneInfo,
            pc_research_financial=Mock(return_value=saved),calculate_ttm=calculate,
            price_history_with_fallback=Mock(side_effect=DataError('price unavailable')),
            api_key=lambda key:'configured' if key=='DART_CRTFC_KEY' else '',
            account_settings=lambda:{'key':'','secret':'','cano':'','product':''},DataError=DataError,
            BrokerError=BrokerError))
        item=ns['watch_fetch']('214450',provider,date(2026,10,20),progress=progress)
        return item,provider,progress

    def test_failed_market_lookup_keeps_pc_ttm_and_never_retries_dart(self):
        item,provider,progress=self.collect(saved_financial())
        provider.latest_period_metrics.assert_not_called()
        provider.corp.assert_not_called();provider.dart.assert_not_called()
        self.assertAlmostEqual(item['pc_ttm']['eps'],17872.55402762442)
        self.assertAlmostEqual(item['pc_ttm']['per'],14.79922788825704)
        self.assertIsNone(item['metrics'])
        self.assertIn('price',item['errors'])
        self.assertTrue(item['report']['disclosures'])
        self.assertGreater(progress.call_count,1)

    def test_no_pc_snapshot_returns_explicit_missing_reason_without_live_dart(self):
        item,provider,_=self.collect(None)
        self.assertIn('PC 수집기',item['errors']['metrics'])
        self.assertNotIn('pc_ttm',item)
        provider.corp.assert_not_called()

    def test_report_export_keeps_actual_pc_provenance(self):
        import json
        item,_,_=self.collect(saved_financial())
        payload=json.loads(export_review(item,[],{},'코스닥'))
        self.assertEqual(payload['official_data']['financial_snapshot']['code'],'214450')
        self.assertEqual(len(payload['official_data']['pc_ttm']['source_inputs']),3)
        self.assertIsNone(payload['official_data']['metrics'])
