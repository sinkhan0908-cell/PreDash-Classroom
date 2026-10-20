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
