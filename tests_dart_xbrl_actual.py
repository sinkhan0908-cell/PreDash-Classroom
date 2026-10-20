"""Regression against the actual failing 2026 half-year DART filing."""
import io
import zipfile
import unittest
from datetime import date
from pathlib import Path
from predash.dart_xbrl import parse
from predash.ttm import TtmError

FIXTURE = Path(__file__).parent / 'tests_fixtures/pharma-20260814002997-eps.xbrl'
PERIODS = [('2026-01-01', '2026-06-30'), ('2025-01-01', '2025-06-30')]


def zipped(body):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('filing.xbrl', body)
    return output.getvalue()


class ActualDartXbrlTests(unittest.TestCase):
    def parse(self, body):
        return parse(zipped(body), PERIODS, '20260814002997', date(2026, 10, 20))

    def test_real_https_taxonomy_and_basic_weighted_shares(self):
        rows = self.parse(FIXTURE.read_bytes())
        self.assertEqual([r['reported_eps'] for r in rows], [10024, 8044])
        self.assertEqual([r['profit'] for r in rows], [104146677079, 83578088330])
        self.assertEqual([r['weighted_shares'] for r in rows], [10389648, 10389648])
        for row in rows:
            self.assertLess(abs(row['profit']/row['weighted_shares']-row['reported_eps']), 1)

    def test_same_taxonomy_with_http_remains_supported(self):
        self.assertEqual(len(self.parse(FIXTURE.read_bytes().replace(b'https://xbrl.ifrs.org/', b'http://xbrl.ifrs.org/'))), 2)

    def test_untrusted_taxonomy_is_rejected(self):
        for namespace in (b'https://xbrl.ifrs.org.evil.test/', b'https://example.org/'):
            with self.assertRaises(TtmError):
                self.parse(FIXTURE.read_bytes().replace(b'https://xbrl.ifrs.org/', namespace))

    def test_diluted_share_count_cannot_replace_basic_shares(self):
        from xml.etree import ElementTree as ET
        root = ET.fromstring(FIXTURE.read_bytes())
        for fact in list(root):
            if fact.tag.endswith('}WeightedAverageShares'):
                root.remove(fact)
        with self.assertRaises(TtmError):
            self.parse(ET.tostring(root))

    def test_basic_share_unit_must_be_shares(self):
        body = FIXTURE.read_bytes().replace(b'unitRef="SHARES"', b'unitRef="KRW"')
        with self.assertRaises(TtmError):
            self.parse(body)


class ActualAnnualAndTtmTests(unittest.TestCase):
    def body(self, receipt):
        return (FIXTURE.parent / ('pharma-' + receipt + '-eps.xbrl')).read_bytes()

    def annual(self, body=None):
        return parse(zipped(body or self.body('20260319001417')), [('2025-01-01', '2025-12-31')],
                     '20260319001417', date(2026, 10, 20))

    def test_actual_ordinary_note_wins_over_unclassified_statement_scope(self):
        row = self.annual()[0]
        self.assertEqual(row['reported_eps'], 15893)
        self.assertEqual(row['profit'], 165120956459)
        self.assertEqual(row['weighted_shares'], 10389648)
        self.assertEqual(row['context_scope'], 'explicit_consolidated_ordinary_shares')

    def test_unclassified_eps_cannot_substitute_missing_ordinary_eps(self):
        from xml.etree import ElementTree as ET
        root = ET.fromstring(self.body('20260319001417'))
        for fact in list(root):
            if fact.tag.endswith('}BasicEarningsLossPerShare') and 'OrdinarySharesMember' in fact.get('contextRef', ''):
                root.remove(fact)
        with self.assertRaises(TtmError):
            self.annual(ET.tostring(root))

    def test_conflict_inside_ordinary_context_remains_an_error(self):
        from xml.etree import ElementTree as ET
        from copy import deepcopy
        root = ET.fromstring(self.body('20260319001417'))
        for fact in list(root):
            if fact.tag.endswith('}BasicEarningsLossPerShare') and 'OrdinarySharesMember' in fact.get('contextRef', ''):
                duplicate = deepcopy(fact); duplicate.text = '9999'; root.append(duplicate)
        with self.assertRaises(TtmError):
            self.annual(ET.tostring(root))

    def test_actual_two_filings_collect_calculate_and_cloud_roundtrip(self):
        from copy import deepcopy
        from unittest.mock import Mock, patch
        from predash.dart_xbrl import collect
        from predash.ttm import calculate
        from predash.pc_collector import collect_and_save
        from predash.financial_store import persist, select_snapshot
        import tests_financial_store as store_tests
        fixture = store_tests.FinancialStoreTests(); fixture.setUp()
        saved = deepcopy(fixture.saved)
        saved['data']['code'] = '214450'
        saved['source'] = 'KIS'
        # Independently checked IR annual EPS used by the collector's crosscheck.
        saved['ttm'] = {'version': 1, 'code': '214450', 'annual_eps_status': 'success',
                        'annual_eps': [{'period_start': '2025-01-01', 'period_end': '2025-12-31', 'reported_eps': 15893}]}
        saved['quote'] = {'close': 277500, 'date': '2026-10-19', 'source': 'fixture',
                          'fetched_at': '2026-10-20T10:00:00+09:00'}
        persist(fixture.client, '214450', saved)
        provider = Mock()
        provider.dart.return_value = {'total_page': 1, 'list': [
            {'corp_code': '00970453', 'corp_name': '파마리서치', 'stock_code': '214450',
             'report_nm': '반기보고서 (2026.06)', 'rcept_no': '20260814002997'},
            {'corp_code': '00970453', 'corp_name': '파마리서치', 'stock_code': '214450',
             'report_nm': '사업보고서 (2025.12)', 'rcept_no': '20260319001417'}]}
        def real_collect(provider, today, annual, **kwargs):
            return collect(provider, today, annual, read=lambda p, receipt, report: zipped(self.body(receipt)), **kwargs)
        with patch('predash.pc_collector.dart_xbrl.collect', side_effect=real_collect):
            result = collect_and_save(fixture.client, provider, '214450', date(2026, 10, 20))
        provider.corp.assert_called_once_with('214450')
        self.assertAlmostEqual(result['eps'], 17872.55402762442)
        restored = select_snapshot(fixture.db['payload'], '214450')
        valuation = calculate(restored['ttm'], restored['quote'], date(2026, 10, 20))
        self.assertAlmostEqual(valuation['per'], 15.52660014741523)
        self.assertEqual((valuation['period_start'], valuation['period_end']), ('2025-07-01', '2026-06-30'))
        self.assertEqual(restored['data'], saved['data'])
        self.assertEqual(fixture.db['payload']['journal'], [{'note': 'preserve'}])
        self.assertEqual(restored['ttm']['xbrl_reader_version'], 3)
