import types
import sys
import unittest
from unittest.mock import patch

try:
    import requests
except ImportError:
    sys.modules['requests'] = types.SimpleNamespace(RequestException=Exception, request=None)

import predash.official as module
from predash.company_codes import KNOWN_COMPANIES


def response(hint, code, **changes):
    info = {'status': '000', 'corp_code': hint['corp_code'], 'stock_code': code,
            'corp_name': hint['names'][0], 'acc_mt': '12', **changes}
    return types.SimpleNamespace(json=lambda: info)


class CompanyCodeTests(unittest.TestCase):
    def setUp(self):
        module._COMPANY_CACHE.clear()
    def tearDown(self):
        module._COMPANY_CACHE.clear()

    def test_registered_stocks_never_download_full_directory_even_after_restart(self):
        for code, hint in KNOWN_COMPANIES.items():
            with self.subTest(code=code), patch.object(module, '_DIRECTORY_CACHE', None), patch.object(module, 'get', return_value=response(hint, code)) as get:
                for _ in range(2):
                    client = module.Official('test-not-a-real-key', '')
                    self.assertEqual(client.corp(code), hint['corp_code'])
                    self.assertEqual(client.dart('company.json', corp_code=hint['corp_code'])['stock_code'], code)
                    self.assertEqual(client.corp(code), hint['corp_code'])
                self.assertEqual(get.call_count, 1)
                self.assertTrue(all(c.args[0].endswith('/company.json') for c in get.call_args_list))
                self.assertIsNone(module._DIRECTORY_CACHE)

    def test_identity_mismatch_or_missing_identity_stops_without_fallback(self):
        code, hint = '005930', KNOWN_COMPANIES['005930']
        for changes in ({'stock_code': '000660'}, {'stock_code': None}, {'corp_code': '99999999'}, {'corp_name': '다른기업'}):
            with self.subTest(changes=changes), patch.object(module, 'get', return_value=response(hint, code, **changes)) as get:
                client = module.Official('test', '')
                with self.assertRaisesRegex(module.DataError, '일치하지'):
                    client.corp(code)
                self.assertEqual(client.verified_companies, {})
                self.assertEqual(get.call_count, 1)

    def test_company_failure_is_retried_on_next_click_not_cached(self):
        hint = KNOWN_COMPANIES['005930']
        with patch.object(module, 'get', side_effect=[module.DataError('기업개황 timeout'), response(hint, '005930')]) as get:
            client = module.Official('test', '')
            with self.assertRaises(module.DataError):
                client.corp('005930')
            self.assertEqual(client.corp('005930'), hint['corp_code'])
            self.assertEqual(get.call_count, 2)

    def test_key_failure_propagates_and_returned_company_cannot_mutate_validation(self):
        hint = KNOWN_COMPANIES['000660']
        with patch.object(module, 'get', return_value=types.SimpleNamespace(json=lambda: {'status': '010'})):
            with self.assertRaisesRegex(module.DataError, '등록되지 않은 DART 키'):
                module.Official('test', '').corp('000660')
        with patch.object(module, 'get', return_value=response(hint, '000660', corp_name='에스케이하이닉스(주)')):
            client = module.Official('test', '')
            corp = client.corp('000660')
            info = client.dart('company.json', corp_code=corp)
            info['stock_code'] = 'wrong'
            self.assertEqual(client.dart('company.json', corp_code=corp)['stock_code'], '000660')
