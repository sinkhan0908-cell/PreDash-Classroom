import ast
import json
import unittest
from pathlib import Path
from unittest.mock import Mock

from predash.financial_validation import strategy_checks, export_validation


def fixture():
    rows, opening = [], []
    for index, year in enumerate(range(2021, 2026)):
        source = f'https://dart.fss.or.kr/dsaf001/main.do?rcpNo={year+1}0319000011'
        base = {'year': year, 'report_code': '11011', 'basis': 'CFS', 'period_end': f'{year}-12-31',
                'source': source, 'receipt': f'{year+1}0319000011', 'fetched_at': '2026-10-12', 'data_gap': None}
        for metric, value in {'매출': 100 * 2**index, '기본 EPS': 10 * 2**index,
                              '지배주주순이익': 30, '지배주주자본': 200,
                              '영업이익': 10, '영업현금흐름': 20}.items():
            rows.append({**base, 'metric': metric, 'value': value, 'unit': '원/주' if metric == '기본 EPS' else '원',
                         'period_type': '기말' if metric == '지배주주자본' else '연간'})
        opening.append({**base, 'metric': '기초 지배주주자본', 'value': 100, 'unit': '원',
                        'period_end': f'{year-1}-12-31', 'period_type': '전기말 · 당기 기초자본'})
    return {'code': '005930', 'asof': '2026-10-12', 'fetched_at': '2026-10-12', 'basis': 'CFS',
            'rows': rows, 'opening_equity': opening, 'data_gaps': []}


class StrategyEvidenceTests(unittest.TestCase):
    def calculate(self, data):
        return strategy_checks(data, 1600, '2026-10-12', 'KIS', evaluation_date='2026-10-13')

    def test_operands_reproduce_six_results_and_survive_export(self):
        data = fixture()
        result = self.calculate(data)
        expected = [100, 100, 0.1, 20, 10, 20]
        for check, value in zip(result['checks'], expected):
            self.assertAlmostEqual(check['value'], value)
            self.assertAlmostEqual(check['evidence']['result'], value)
            self.assertIsNone(check['evidence']['blocked_reason'])
        roe = result['checks'][3]['evidence']
        self.assertEqual(len(roe['inputs']), 15)
        self.assertTrue(all(r['계산한 ROE(%)'] == 20 for r in roe['intermediates']))
        self.assertEqual(roe['inputs'][1]['period_end'], '2020-12-31')
        self.assertIn('성장 구간 4년', result['checks'][0]['evidence']['steps'][0])
        self.assertIn('성장 구간 3년', result['checks'][1]['evidence']['steps'][0])
        payload = json.loads(json.dumps(export_validation(data, result), allow_nan=False))
        self.assertEqual(payload['strategy_result']['checks'], result['checks'])

    def test_negative_eps_and_missing_equity_show_blockers_not_zero(self):
        data = fixture()
        next(r for r in data['rows'] if r['metric'] == '기본 EPS' and r['year'] == 2023)['value'] = -10
        data['opening_equity'][2]['value'] = None
        result = self.calculate(data)
        for i in (1, 2, 3):
            evidence = result['checks'][i]['evidence']
            self.assertIsNone(evidence['result'])
            self.assertTrue(evidence['blocked_reason'])
        eps = result['checks'][1]['evidence']['inputs']
        self.assertEqual(next(r for r in eps if r['year'] == 2023)['value'], -10)
        roe = result['checks'][3]['evidence']['inputs']
        self.assertIsNone(next(r for r in roe if r['year'] == 2023 and r['metric'] == '기초 지배주주자본')['value'])

    def test_annual_sources_exclude_same_year_interim_eps(self):
        data = fixture()
        data['rows'].insert(0, {'year': 2025, 'metric': '기본 EPS', 'period_type': '누적',
                                'report_code': '11012', 'value': 999, 'source': 'wrong interim'})
        result = self.calculate(data)
        for i in (1, 2):
            self.assertNotIn('wrong interim', [r['source'] for r in result['checks'][i]['evidence']['inputs']])

    def test_expired_quote_exposes_arithmetic_but_no_valid_result(self):
        result = strategy_checks(fixture(), 1600, '2026-10-01', 'KIS', evaluation_date='2026-10-13')
        evidence = result['checks'][2]['evidence']
        self.assertIsNone(evidence['result'])
        self.assertIn('초과', evidence['blocked_reason'])
        self.assertEqual(evidence['inputs'][0]['period_end'], '2026-10-01')
        self.assertEqual(evidence['evaluation_date'], '2026-10-13')

    def test_ui_shows_formula_inputs_and_only_links_actual_urls(self):
        tree = ast.parse(Path('app.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'strategy_evidence_panel')
        st = Mock()
        st.checkbox.return_value = True
        st.selectbox.return_value = 2
        namespace = {'st': st}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'app.py', 'exec'), namespace)
        namespace['strategy_evidence_panel'](self.calculate(fixture()), '005930', 'watch')
        self.assertEqual(st.dataframe.call_count, 2)
        self.assertTrue(all(call.args[1].startswith('https://dart.fss.or.kr/') for call in st.link_button.call_args_list))
        self.assertTrue(any('개별 시세 원문 URL 미확인' in str(call) for call in st.caption.call_args_list))
