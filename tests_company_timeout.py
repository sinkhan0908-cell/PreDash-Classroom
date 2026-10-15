import unittest
import types
from unittest.mock import patch
import predash.official as module
from tests_company_codes import response
from predash.company_codes import KNOWN_COMPANIES

class CompanyTimeoutTests(unittest.TestCase):
    def setUp(self): module._COMPANY_CACHE.clear()
    def tearDown(self): module._COMPANY_CACHE.clear()
    def xml(self, **changes):
        info={'status':'000','corp_code':'00126380','stock_code':'005930','corp_name':'삼성전자','acc_mt':'12',**changes}
        return types.SimpleNamespace(content=('<result>'+''.join(f'<{k}>{v}</{k}>' for k,v in info.items())+'</result>').encode())
    def test_timeout_falls_back_to_documented_xml_and_reuses_verified_metadata(self):
        with patch.object(module,'get',side_effect=[module.DataError('DART 기업개황: 응답 시간이 초과됐습니다.'),self.xml()]) as get:
            for _ in range(2): self.assertEqual(module.Official('test','').corp('005930'),'00126380')
            self.assertEqual(get.call_count,2)
            self.assertTrue(get.call_args.args[0].endswith('company.xml'))
    def test_both_failed_not_cached_and_next_request_can_recover(self):
        with patch.object(module,'get',side_effect=[module.DataError('응답 시간이 초과'),module.DataError('XML 응답 시간이 초과'),response(KNOWN_COMPANIES['005930'],'005930')]) as get:
            with self.assertRaisesRegex(module.DataError,'XML'): module.Official('test','').corp('005930')
            self.assertFalse(module._COMPANY_CACHE)
            self.assertEqual(module.Official('test','').corp('005930'),'00126380')
            self.assertEqual(get.call_count,3)
    def test_identity_mismatch_fallback_not_cached(self):
        with patch.object(module,'get',side_effect=[module.DataError('응답 시간이 초과'),self.xml(stock_code='000660')]):
            with self.assertRaisesRegex(module.DataError,'일치하지'):module.Official('test','').corp('005930')
            self.assertFalse(module._COMPANY_CACHE)
    def test_authentication_error_does_not_fallback(self):
        with patch.object(module,'get',return_value=types.SimpleNamespace(json=lambda:{'status':'010'})) as get:
            with self.assertRaisesRegex(module.DataError,'키'):module.Official('test','').corp('005930')
            self.assertEqual(get.call_count,1)
    def test_expiry_key_isolation_and_copy(self):
        with patch.object(module,'get',return_value=response(KNOWN_COMPANIES['005930'],'005930')) as get,patch.object(module.time,'monotonic',return_value=100) as clock:
            a=module.Official('first','');a.corp('005930')
            payload=a.dart('company.json',corp_code='00126380');payload['acc_mt']='01'
            self.assertEqual(a.dart('company.json',corp_code='00126380')['acc_mt'],'12')
            module.Official('second','').corp('005930')
            self.assertEqual(get.call_count,2)
            clock.return_value=100+module.COMPANY_TTL_SECONDS+1
            module.Official('first','').corp('005930')
            self.assertEqual(get.call_count,3)
            self.assertNotIn('first',str(module._COMPANY_CACHE))
    def test_financial_responses_not_reused_by_metadata_cache(self):
        with patch.object(module,'get',return_value=types.SimpleNamespace(json=lambda:{'status':'000','list':[]})) as get:
            a=module.Official('test','')
            for _ in range(2):a.dart('fnlttSinglAcntAll.json',corp_code='00126380')
            self.assertEqual(get.call_count,2)
