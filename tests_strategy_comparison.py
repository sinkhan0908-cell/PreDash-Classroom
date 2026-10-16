import unittest
from copy import deepcopy

from predash.strategy_comparison import comparison_group, build_comparison, table_html
from tests_strategy_evidence import fixture


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.data = fixture()
        self.data['name'] = '공개기업'
        for row in self.data['rows']:
            row['currency'] = 'KRW'
        self.group = comparison_group(self.data)

    def build(self, data=None, quotes=None, unavailable=None):
        return build_comparison(['005930'], {'005930': data or self.data}, quotes or {}, {},
                                unavailable or {}, self.group, '2026-10-14')[0]

    def test_same_basis_and_period_only_and_missing_currency_not_assumed(self):
        self.assertEqual(self.group, '2021~2025년 · CFS · KRW')
        for field, value in [('basis', 'OFS'), ('basis', '미확인')]:
            data = deepcopy(self.data)
            data[field] = value
            self.assertIsNone(self.build(data)['result'])
        data = deepcopy(self.data)
        data['rows'][0]['currency'] = 'USD'
        self.assertIn('통화', self.build(data)['reason'])

    def test_missing_expired_and_failed_snapshots_never_produce_current_results(self):
        self.assertIsNone(self.build(unavailable={'005930': '조회 실패'})['result'])
        row = build_comparison(['000660'], {}, {}, {}, {}, self.group, '2026-10-14')[0]
        self.assertEqual(row['reason'], '재무자료 조회 전')

    def test_price_failure_keeps_financial_checks_and_stale_price_holds_peg(self):
        result = self.build()['result']
        self.assertEqual(result['summary']['completed'], 5)
        self.assertEqual(result['checks'][2]['status'], '판정 보류')
        result = self.build(quotes={'005930': {'close': 1600, 'date': '2026-10-01', 'source': 'KIS'}})['result']
        self.assertIn('초과', result['checks'][2]['reason'])

    def test_table_roe_and_peg_headers_match_values_and_escape_external_text(self):
        self.data['name'] = '<script>alert(1)</script>'
        row = self.build(quotes={'005930': {'close': 1600, 'date': '2026-10-13', 'source': 'KIS'}})
        rendered = table_html([row])
        self.assertLess(rendered.index('20.00%'), rendered.index('0.10배'))
        self.assertNotIn('<script>', rendered)

    def test_partial_sales_do_not_compare_shorter_cagr_as_five_years(self):
        data = deepcopy(self.data)
        next(r for r in data['rows'] if r['year'] == 2021 and r['metric'] == '매출')['value'] = None
        result = self.build(data)['result']
        self.assertIsNone(result['checks'][0]['value'])
        self.assertEqual(result['checks'][0]['display_status'], '데이터 부족')
        self.assertIsNone(result['checks'][0]['evidence']['result'])

