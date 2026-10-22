"""Official filing facts, source anchoring and stale-writer preservation."""
import unittest
from copy import deepcopy
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as E
from predash import business_metrics as b
from tests_dart_xbrl_actual import zipped

FIXTURE=Path(__file__).parent/'tests_fixtures/pharma-20260814002997-eps.xbrl'
TODAY=date(2026,10,22)

def block(body=None):
    return b.parse(zipped(body or FIXTURE.read_bytes()),'214450','00970453',2026,2,'20260814002997',TODAY,
                   fetched_at='2026-10-20T17:39:02+09:00')

def ttm():
    value=block()
    return {'status':'success','code':'214450','business_metrics':value,
            'inputs':[{k:value[k] for k in ('receipt','document_sha256','period_end')}]}

class BusinessMetricsTests(unittest.TestCase):
    def test_verified_cumulative_and_quarter_are_separate(self):
        value=b.view(ttm(),'214450',TODAY)
        self.assertAlmostEqual(value['revenue'],3248.05059793)
        self.assertAlmostEqual(value['profit'],1237.62004754)
        self.assertAlmostEqual(value['revenue_growth_pct'],26.1293556769)
        self.assertAlmostEqual(value['growth_pct'],23.0100749418)
        self.assertAlmostEqual(value['standalone']['revenue'],1787.04799285)
        self.assertAlmostEqual(value['standalone']['profit'],664.69662181)
        self.assertEqual(value['fetched'],'2026-10-20T17:39:02+09:00')

    def test_missing_units_or_concepts_never_become_zero(self):
        for replacement in ((b'>KRW<',b'>USD<'),(b'}Revenue',b'}Unknown')):
            root=E.fromstring(FIXTURE.read_bytes())
            for f in root:
                if replacement[0]==b'>KRW<' and f.tag.endswith('}unit'):
                    for measure in f:measure.text='iso4217:USD'
                elif replacement[0]==b'}Revenue' and f.tag.endswith('}Revenue'):f.tag=f.tag.replace('}Revenue','}Unknown')
            with self.assertRaises(b.BusinessError):block(E.tostring(root))

    def test_conflicting_total_rejected(self):
        root=E.fromstring(FIXTURE.read_bytes())
        context=block()['rows'][0]['contexts']['revenue']
        target=next(f for f in root if f.tag.endswith('}Revenue') and f.get('contextRef')==context)
        duplicate=deepcopy(target);duplicate.text='1';root.append(duplicate)
        with self.assertRaises(b.BusinessError):block(E.tostring(root))

    def test_wrong_company_and_report_anchor_hidden(self):
        with self.assertRaises(b.BusinessError):
            b.parse(zipped(FIXTURE.read_bytes()),'214450','00000001',2026,2,'20260814002997',TODAY)
        for field,value in [('document_sha256','0'*64),('receipt','20260814000000'),('period_end','2026-03-31')]:
            saved=ttm();saved['inputs'][0][field]=value
            self.assertIsNone(b.view(saved,'214450',TODAY))
        self.assertIsNone(b.view(ttm(),'214450',date(2026,8,1)))

    def test_nonpositive_prior_does_not_invent_growth(self):
        saved=ttm()
        for row in saved['business_metrics']['rows']:
            if row['period_start']=='2025-01-01':row.update(revenue=0,operating_profit=-10)
        value=b.view(saved,'214450',TODAY)
        self.assertIsNone(value['revenue_growth_pct']);self.assertIsNone(value['growth_pct'])

    def test_pc_missing_business_does_not_persist(self):
        from unittest.mock import Mock,patch
        from predash import pc_collector as pc
        client=Mock();client.load.return_value={'payload':{}}
        saved={'ttm':{'annual_eps_status':'success','annual_eps':[{}]},'data':{'code':'214450'}}
        with patch.object(pc,'select_snapshot',return_value=saved),patch.object(pc.dart_xbrl,'collect',return_value={'status':'success'}),patch.object(pc.ttm,'calculate',return_value={'eps':10}),patch.object(pc,'persist') as persist:
            with self.assertRaises(b.BusinessError):pc.collect_and_save(client,Mock(),'214450',TODAY)
            persist.assert_not_called()

    def test_old_price_writer_preserves_business_for_matching_report(self):
        import tests_financial_store as fixtures
        from predash.financial_store import persist,select_snapshot
        f=fixtures.FinancialStoreTests();f.setUp()
        saved=deepcopy(f.saved);saved['data']['code']='214450';saved['ttm']=ttm()
        persist(f.client,'214450',saved)
        incoming=deepcopy(saved);incoming['ttm'].pop('business_metrics')
        persist(f.client,'214450',incoming,attempt_kind='price')
        self.assertIsNotNone(b.view(select_snapshot(f.db['payload'],'214450')['ttm'],'214450',TODAY))
