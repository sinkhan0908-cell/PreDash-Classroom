import unittest
from copy import deepcopy
from datetime import date
from unittest.mock import Mock, patch
from predash import pc_collector as pc
from predash.cloud_store import StorageError
from predash.official import DataError
import tests_financial_store as store_tests


class PcCollectorTests(unittest.TestCase):
    def setUp(self):
        fixture = store_tests.FinancialStoreTests(); fixture.setUp()
        self.saved = deepcopy(fixture.saved)
        self.saved['data']['code'] = '214450'
        self.saved['ttm'] = {'code': '214450', 'annual_eps_status': 'success', 'annual_eps': [{'year': 2025}]}
        self.provider = Mock()
        self.client = Mock()
        self.client.load.return_value = {'payload': {}}
        self.block = {'status': 'success', 'version': 1, 'inputs': []}

    def run_collection(self, status='success', eps=10):
        block = {**self.block, 'status': status}
        with patch.object(pc, 'select_snapshot', side_effect=[deepcopy(self.saved), {'ttm': {**block, 'collector_version': pc.ttm.COLLECTOR_VERSION}}]), \
             patch.object(pc.dart_xbrl, 'collect', return_value=block), \
             patch.object(pc.ttm, 'calculate', return_value={'eps': eps}), \
             patch.object(pc, 'persist', return_value={'payload': {}}) as persist:
            if status != 'success' or eps is None:
                with self.assertRaises(ValueError):
                    pc.collect_and_save(self.client, self.provider, '214450', date(2026, 10, 20))
                persist.assert_not_called()
            else:
                pc.collect_and_save(self.client, self.provider, '214450', date(2026, 10, 20))
                saved = persist.call_args.args[2]
                self.assertEqual(saved['data'], self.saved['data'])
                self.assertEqual(saved['quote'], self.saved['quote'])
                self.assertEqual(persist.call_args.kwargs['attempt_kind'], 'ttm')

    def test_validated_ttm_preserves_annual_inputs_and_price_dates(self):
        self.run_collection()

    def test_failed_block_and_invalid_calculation_never_write(self):
        self.run_collection(status='failed')
        self.run_collection(eps=None)

    def test_identity_failure_prevents_fetch_and_write(self):
        self.provider.corp.side_effect = DataError('company unavailable')
        with patch.object(pc, 'select_snapshot', return_value=self.saved), patch.object(pc, 'persist') as persist:
            with self.assertRaises(DataError):
                pc.collect_and_save(self.client, self.provider, '214450', date(2026, 10, 20))
            persist.assert_not_called()

    def test_error_does_not_echo_credentials(self):
        with patch('builtins.input', side_effect=['https://test.supabase.co', '214450']), \
             patch.object(pc, 'getpass', side_effect=['sb_secret_PRIVATE', 'a'*40]), \
             patch.object(pc, 'collect_and_save', side_effect=StorageError('PRIVATE')), \
             patch('builtins.print') as output:
            self.assertEqual(pc.main(), 1)
            self.assertNotIn('PRIVATE', str(output.call_args_list))

    def test_diagnostic_exposes_only_known_literal_reasons(self):
        known = 'XBRL 연결 보통주 기본 EPS 계정·기간·단위 누락 또는 불일치'
        self.assertIn(known, pc.diagnostic(pc.ttm.TtmError(known)))
        for error in (ValueError('https://example.com?crtfc_key=PRIVATE'), DataError('PRIVATE'), StorageError('PRIVATE')):
            self.assertNotIn('PRIVATE', pc.diagnostic(error))
