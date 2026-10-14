import unittest
import ast
import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import Mock
from copy import deepcopy

from predash.strategy_comparison import comparison_group, build_comparison, table_html
from tests_strategy_evidence import fixture
from predash.official import DataError


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

    def test_page_refresh_continues_after_one_company_fails_and_drops_old_quote(self):
        st = Mock()
        st.session_state = {'watch_codes': ['005930', '000660'], 'watch_names': {},
                            'comparison_quote_000660': {'close': 999, 'date': '2026-10-13', 'source': 'old'}}
        st.query_params = {}
        st.multiselect.return_value = ['005930', '000660']
        st.checkbox.return_value = False
        st.button.return_value = True
        st.selectbox.side_effect = lambda label, options, **kw: list(options)[0]
        st.radio.return_value = '전체'
        memory = Mock()
        memory.get.side_effect = [(self.data, '저장 자료 재사용'), DataError('기업개황 timeout')]
        memory.remaining.return_value = 100
        quote = Mock(side_effect=[(1600, '20261013', '공개기업', 'KIS'), DataError('시세 timeout')])
        ns = dict(st=st, clean_codes=lambda x: list(dict.fromkeys(c for c in x if c)),
                  datetime=datetime, ZoneInfo=ZoneInfo, public_financial_cache=lambda: memory,
                  api_key=lambda k: 'configured', official_client=Mock(), DataError=DataError,
                  price_sources_ready=lambda: True, quote_with_fallback=quote,
                  comparison_group=comparison_group, build_comparison=build_comparison,
                  table_html=table_html, strategy_evidence_panel=Mock(), json=json,
                  re=__import__('re'))
        tree = ast.parse(Path('app.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'strategy_comparison_page')
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'app.py', 'exec'), ns)
        ns['strategy_comparison_page']()
        self.assertEqual(memory.get.call_count, 2)
        self.assertEqual(st.session_state['comparison_quote_005930']['date'], '2026-10-13')
        self.assertIsNone(st.session_state['comparison_quote_000660']['close'])
        exported = json.loads(st.download_button.call_args.args[1])
        self.assertEqual(len(exported['items']), 2)
        self.assertIsNone(exported['items'][1]['result'])
        self.assertIn('timeout', exported['items'][1]['reason'])
