import json
import ast
import unittest
from pathlib import Path
from contextlib import nullcontext
from datetime import date
from unittest.mock import Mock

from predash.financial_validation import parse_statement, collect
from predash.official import Official, DataError


def row(account, value, section='IS', **kwargs):
    return dict(sj_div=section, account_id=account, thstrm_amount=value,
                currency='KRW', rcept_no='20260814000001', **kwargs)


class FinancialValidationTests(unittest.TestCase):
    def parse(self, rows, report='11012'):
        return {r['metric']: r for r in parse_statement(rows, 2026, report, 'CFS', '2026-10-08')}

    def test_half_year_uses_cumulative_eps_keeps_per_share_units(self):
        data = self.parse([
            row('ifrs-full_Revenue', '120', thstrm_add_amount='200'),
            row('ifrs-full_BasicEarningsLossPerShare', '3.1', thstrm_add_amount='5.25'),
            row('ifrs-full_CashFlowsFromUsedInOperatingActivities', '(30)', 'CF')])
        self.assertEqual(data['매출']['value'], 200)
        self.assertEqual(data['기본 EPS']['value'], 5.25)
        self.assertEqual(data['기본 EPS']['unit'], '원/주')
        self.assertEqual(data['영업현금흐름']['value'], -30)
        self.assertEqual(data['매출']['period_end'], '2026-06-30')
        self.assertIsNone(data['자본총계']['value'])

    def test_missing_cumulative_never_substitutes_quarter(self):
        data = self.parse([row('ifrs-full_Revenue', '120')])
        self.assertIsNone(data['매출']['value'])
        self.assertTrue(data['매출']['data_gap'])

    def test_conflicting_duplicates_hold_eps(self):
        data = self.parse([row('ifrs-full_BasicEarningsLossPerShare', '2', thstrm_add_amount=v) for v in ('17,902', '17,950')])
        self.assertIsNone(data['기본 EPS']['value'])
        self.assertIn('서로 다름', data['기본 EPS']['data_gap'])

    def test_bad_currency_and_nonfinite_are_not_numbers(self):
        bad = row('ifrs-full_Revenue', '2', thstrm_add_amount='20')
        bad['currency'] = 'USD'
        data = self.parse([bad, row('dart_OperatingIncomeLoss', '3', thstrm_add_amount='NaN')])
        self.assertIsNone(data['매출']['value'])
        self.assertIsNone(data['영업이익']['value'])
        json.dumps(data, allow_nan=False)

    def test_balance_equation_and_loss_zero_retained(self):
        data = self.parse([row('ifrs-full_Assets', '100', 'BS'), row('ifrs-full_Liabilities', '40', 'BS'),
                           row('ifrs-full_Equity', '50', 'BS'), row('dart_OperatingIncomeLoss', '-3', thstrm_add_amount='-10'),
                           row('ifrs-full_Revenue', '0', thstrm_add_amount='0')])
        self.assertIsNone(data['자산총계']['value'])
        self.assertEqual(data['영업이익']['value'], -10)
        self.assertEqual(data['매출']['value'], 0)

    def test_unknown_fiscal_period_and_future_filing_hold(self):
        rows = [row('ifrs-full_Revenue', '100')]
        self.assertTrue(all(r['value'] is None for r in parse_statement(rows, 2025, '11011', 'CFS', '2026-10-08', False)))
        self.assertTrue(all(r['value'] is None for r in parse_statement(rows, 2025, '11011', 'CFS', '2026-01-01')))

    def test_response_period_mismatch_holds(self):
        data = self.parse([row('ifrs-full_Revenue', '100', bsns_year='2025', thstrm_add_amount='200')])
        self.assertIsNone(data['매출']['value'])
        self.assertIn('불일치', data['매출']['data_gap'])

    def test_failed_ui_refresh_removes_old_result(self):
        # Execute the actual UI function with a tiny Streamlit boundary stub.
        tree = ast.parse(Path('app.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'financial_validation_panel')
        st = Mock()
        st.session_state = {'financial_validation_005930': {'old': 'result'}}
        st.expander.return_value = nullcontext()
        st.spinner.return_value = nullcontext()
        st.button.return_value = True
        namespace = {'st': st, 'api_key': lambda key: 'configured', 'official_client': Mock(),
                     'collect_financial_validation': Mock(side_effect=DataError('조회 실패')), 'DataError': DataError}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'app.py', 'exec'), namespace)
        namespace['financial_validation_panel']('005930', 'watch')
        self.assertNotIn('financial_validation_005930', st.session_state)
        st.warning.assert_called_once_with('조회 실패')

    def test_five_years_same_basis_and_no_price_calls(self):
        provider = Mock()
        provider.corp.return_value = '00126380'
        def dart(endpoint, **params):
            if endpoint == 'company.json':
                return {'acc_mt': '12', 'corp_name': '공개기업'}
            year, report = int(params['bsns_year']), params['reprt_code']
            if report != '11011' or year > 2025:
                return None
            return {'list': [dict(row('ifrs-full_Revenue', '100'), rcept_no=f'{year+1}0315000001')]}
        provider.dart.side_effect = dart
        data = collect(provider, '005930', date(2026, 4, 8))
        self.assertEqual({r['year'] for r in data['rows']}, {2021, 2022, 2023, 2024, 2025})
        self.assertEqual({r['basis'] for r in data['rows']}, {'CFS'})
        provider.price.assert_not_called()
        self.assertTrue(data['data_gaps'])

    def test_price_and_disclosure_failure_keep_financial_report(self):
        provider = Official('', '')
        provider.corp = Mock(return_value='00126380')
        provider.price = Mock(side_effect=DataError('HTTP 403'))
        provider.annual = lambda corp, year, basis: {'year': year, 'revenue': 100, 'profit': 10}
        provider.dart = Mock(side_effect=DataError('목록 실패'))
        provider.latest_period_metrics = Mock(return_value={'revenue': 100})
        data = provider.report('005930', 2025, date(2026, 10, 8))
        self.assertIsNone(data['price'])
        self.assertEqual(len(data['years']), 3)
        self.assertEqual(data['metrics']['revenue'], 100)
        self.assertEqual(len(data['warnings']), 2)


if __name__ == '__main__':
    unittest.main()
