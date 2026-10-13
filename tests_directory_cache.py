import io
import types
import unittest
import zipfile
from unittest.mock import patch

import predash.official as module


def zipped(xml):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('CORPCODE.xml', xml)
    return types.SimpleNamespace(content=buf.getvalue())


class DirectoryCacheTests(unittest.TestCase):
    def setUp(self):
        self.previous = module._DIRECTORY_CACHE
        module._DIRECTORY_CACHE = None
        self.response = zipped('<result><list><stock_code>005930</stock_code><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name></list></result>')

    def tearDown(self):
        module._DIRECTORY_CACHE = self.previous

    def test_new_clients_share_only_successful_public_directory(self):
        with patch.object(module, 'get', return_value=self.response) as get:
            first = module.Official('fake-one', '')
            second = module.Official('fake-two', '')
            self.assertEqual(first.corp('005930'), '00126380')
            self.assertEqual(second.corp('005930'), '00126380')
            self.assertEqual(get.call_count, 1)
            self.assertNotIn('dart_key', module._DIRECTORY_CACHE)
            second.names['005930'] = 'changed locally'
            self.assertEqual(first.names['005930'], '삼성전자')

    def test_timeout_is_not_cached_and_next_request_can_succeed(self):
        with patch.object(module, 'get', side_effect=[module.DataError('timeout'), self.response]) as get:
            with self.assertRaises(module.DataError):
                module.Official('fake', '').corp('005930')
            self.assertIsNone(module._DIRECTORY_CACHE)
            self.assertEqual(module.Official('fake', '').corp('005930'), '00126380')
            self.assertEqual(get.call_count, 2)

    def test_expired_cache_refreshes_and_empty_zip_is_not_saved(self):
        with patch.object(module, 'get', return_value=self.response) as get:
            module.Official('fake', '').corp('005930')
            module._DIRECTORY_CACHE['loaded_at'] -= module.DIRECTORY_TTL_SECONDS + 1
            module.Official('fake', '').corp('005930')
            self.assertEqual(get.call_count, 2)
        module._DIRECTORY_CACHE = None
        with patch.object(module, 'get', return_value=zipped('<result/>')):
            with self.assertRaises(module.DataError):
                module.Official('fake', '').corp('005930')
            self.assertIsNone(module._DIRECTORY_CACHE)


if __name__ == '__main__':
    unittest.main()
