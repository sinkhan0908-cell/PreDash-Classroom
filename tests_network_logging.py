import types
import unittest
from unittest.mock import Mock,patch
import predash.official as module

class RequestException(Exception): pass
class Timeout(RequestException): pass
class ReadTimeout(Timeout): pass
class ConnectTimeout(Timeout): pass
class ConnectionError(RequestException): pass
class SSLError(ConnectionError): pass

class NetworkLogTests(unittest.TestCase):
    def client(self,exc):
        return types.SimpleNamespace(get=Mock(side_effect=exc),Timeout=Timeout,RequestException=RequestException,
                                     ConnectionError=ConnectionError,exceptions=types.SimpleNamespace(SSLError=SSLError))
    def test_timeout_diagnosis_logs_phase_attempts_not_credentials_or_exception_text(self):
        for kind in (ReadTimeout,ConnectTimeout):
            client=self.client(kind('https://example.invalid/?crtfc_key=DO_NOT_LOG'))
            with patch.object(module,'requests',client),self.assertLogs(module._NETWORK_LOG,level='INFO') as logs:
                with self.assertRaisesRegex(module.DataError,'READ_TIMEOUT' if kind is ReadTimeout else 'CONNECT_TIMEOUT'):
                    module.get('https://opendart.fss.or.kr/api/company.json',{'crtfc_key':'DO_NOT_LOG'})
            self.assertEqual(client.get.call_count,2)
            text=' '.join(logs.output)
            self.assertNotIn('DO_NOT_LOG',text)
            self.assertNotIn('crtfc_key',text)
            self.assertIn('attempt=2',text)
            self.assertIn('elapsed_s=',text)
    def test_dns_nested_type_detected_without_sensitive_message(self):
        import socket
        exc=ConnectionError('DO_NOT_LOG')
        exc.__cause__=socket.gaierror('private-request')
        self.assertEqual(module.failure_phase(exc),'DNS_FAILURE')
    def test_http_denial_logged_without_query_values(self):
        client=self.client(None)
        client.get.side_effect=None
        client.get.return_value=types.SimpleNamespace(status_code=403,content=b'')
        with patch.object(module,'requests',client),self.assertLogs(module._NETWORK_LOG,level='INFO') as logs:
            with self.assertRaisesRegex(module.DataError,'HTTP 403'):
                module.get('https://opendart.fss.or.kr/api/company.json',{'crtfc_key':'DO_NOT_LOG'})
        self.assertIn('http=403',' '.join(logs.output))
        self.assertNotIn('DO_NOT_LOG',' '.join(logs.output))
