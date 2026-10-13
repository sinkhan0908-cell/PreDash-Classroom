import unittest
from unittest.mock import Mock, patch

from predash.financial_cache import FinancialCache
from predash.financial_validation import strategy_checks


class FinancialCacheTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.cache = FinancialCache(clock=lambda: self.now, max_entries=2)
        self.data = {'code': '005930', 'rows': [{'value': 0}], 'data_gaps': [], 'fetched_at': 'original'}
        self.loader = Mock(return_value=self.data)

    def test_reuse_copies_snapshot_without_rewriting_provenance(self):
        first, origin = self.cache.get('005930', self.loader)
        first['rows'][0]['value'] = 99
        second, origin = self.cache.get('005930', self.loader)
        self.assertEqual(origin, '저장 자료 재사용')
        self.assertEqual(second, self.data)
        self.assertEqual(self.loader.call_count, 1)
        self.assertEqual(set(self.cache.entries['005930']), {'data', 'loaded', 'ttl'})

    def test_expiry_force_and_other_codes(self):
        self.cache.get('005930', self.loader)
        self.now = 86400
        self.cache.get('005930', self.loader)
        self.cache.get('005930', self.loader, force=True)
        self.assertEqual(self.loader.call_count, 3)
        for code in ('000660', '214450'):
            self.cache.get(code, lambda: {**self.data, 'code': code})
        self.assertEqual(len(self.cache.entries), 2)
        self.assertNotIn('005930', self.cache.entries)

    def test_partial_data_retried_after_five_minutes(self):
        self.data['data_gaps'] = [{'reason': '계정 누락'}]
        self.cache.get('005930', self.loader)
        self.now = 299
        self.cache.get('005930', self.loader)
        self.assertEqual(self.loader.call_count, 1)
        self.now = 300
        self.cache.get('005930', self.loader)
        self.assertEqual(self.loader.call_count, 2)

    def test_failure_does_not_cache_error_or_extend_old_lifetime(self):
        self.cache.get('005930', self.loader)
        self.now = 86401
        with self.assertRaises(RuntimeError):
            self.cache.get('005930', Mock(side_effect=RuntimeError('timeout')))
        self.assertEqual(self.cache.remaining('005930', 'original'), 0)
        self.cache.get('005930', self.loader)
        self.assertEqual(self.loader.call_count, 2)
        with self.assertRaises(ValueError):
            self.cache.get('000660', self.loader)
        self.assertNotIn('000660', self.cache.entries)

    def test_peg_uses_evaluation_day_not_cached_financial_lookup_day(self):
        rows = [{'year': year, 'metric': '기본 EPS', 'value': value, 'period_type': '연간',
                 'report_code': '11011', 'receipt': '20260319001417'}
                for year, value in zip(range(2022, 2026), (1, 2, 3, 4))]
        data = {'asof': '2026-10-08', 'rows': rows}
        # Include the annual income field used to enumerate financial years.
        rows += [{**r, 'metric': '매출'} for r in rows[:]]
        with patch('predash.financial_validation.quote_date_check', return_value=('종가 만료', 8)) as check:
            result = strategy_checks(data, 100, '2026-10-01', 'official', evaluation_date='2026-10-09')
        self.assertEqual(check.call_args.args[0], '2026-10-09')
        self.assertEqual(result['evaluation_date'], '2026-10-09')
