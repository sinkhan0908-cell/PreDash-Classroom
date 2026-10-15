import unittest
import types
import json
import sys
from unittest.mock import Mock,patch,MagicMock
try: import requests
except ImportError: sys.modules['requests']=types.SimpleNamespace(RequestException=Exception,request=None)
from predash.kis_probe import DemoPublicProbe,demo_keys,run_probe,PRICE,RATIOS
from predash.kis import BrokerError

class ProbeTests(unittest.TestCase):
    def client(self):
        client=DemoPublicProbe({'key':'PRIVATE_KEY','secret':'PRIVATE_SECRET'})
        client.authorize=Mock()
        client.token='PRIVATE_TOKEN'
        return client
    def response(self,data,cont=''):
        return types.SimpleNamespace(headers={'tr_cont':cont}),data
    def test_pair_resolution_does_not_mix_or_use_real_settings(self):
        self.assertEqual(demo_keys({}, {'KIS_ENV':'real','KIS_APP_KEY':'real','KIS_APP_SECRET':'real'}),{'key':'','secret':''})
        self.assertEqual(demo_keys({'mode':'demo','key':'session'}, {'KIS_ENV':'demo','KIS_APP_KEY':'stored','KIS_APP_SECRET':'pair'}),{'key':'stored','secret':'pair'})
        self.assertEqual(demo_keys({}, {'KIS_ENV':'real','KIS_DEMO_APP_KEY':'demo','KIS_DEMO_APP_SECRET':'pair'}),{'key':'demo','secret':'pair'})
    def test_probe_independent_results_and_secret_free_export(self):
        client=self.client()
        client.call=Mock(side_effect=[self.response({'rt_cd':'0','msg_cd':'OK','output':{'eps':'1000','per':'20','stck_prpr':'20000','stck_shrn_iscd':'005930','cano':'PRIVATE_ACCOUNT'}}),
                                     self.response({'rt_cd':'1','msg_cd':'OPSQ0001','msg1':'PRIVATE_SECRET'})])
        r=run_probe(client,'005930',pause=Mock())
        self.assertTrue(r['results'][0]['success']);self.assertFalse(r['results'][1]['success'])
        self.assertEqual(r['results'][1]['message_code'],'OPSQ0001')
        self.assertEqual(client.call.call_count,2)
        for call in client.call.call_args_list:
            self.assertEqual(call.args[0],'GET');self.assertNotIn('cano',call.kwargs['params'])
        for secret in ('PRIVATE_ACCOUNT','PRIVATE_TOKEN','PRIVATE_SECRET','PRIVATE_KEY'):self.assertNotIn(secret,json.dumps(r))
    def test_annual_eps_periods_and_pagination_reported_not_inferred_five_years(self):
        client=self.client()
        client.call=Mock(side_effect=[BrokerError('증권사 연결 실패'),self.response({'rt_cd':'0','output':[{'stac_yymm':'202412','eps':'100'},{'stac_yymm':'202512','eps':'200'},{'stac_yymm':'invalid','eps':'999'}]},'M')])
        r=run_probe(client,'005930',pause=Mock())
        item=r['results'][1]
        self.assertTrue(item['success']);self.assertTrue(item['more_pages'])
        self.assertEqual(len(item['annual_eps']),2)
        self.assertEqual(client.call.call_args.kwargs['params']['FID_DIV_CLS_CODE'],'0')
    def test_no_real_or_trading_endpoints_and_invalid_code_before_auth(self):
        client=self.client()
        with self.assertRaises(BrokerError):client.call('GET','/uapi/domestic-stock/v1/trading/inquire-balance')
        with self.assertRaises(BrokerError):run_probe(client,'not-code')
        client.authorize.assert_not_called()
        client.mode='real'
        with self.assertRaises(BrokerError):run_probe(client,'005930')
    def test_auth_failure_does_not_repeat_or_call_public_apis(self):
        client=self.client();client.authorize.side_effect=BrokerError('토큰 발급 실패')
        client.call=Mock()
        r=run_probe(client,'005930')
        self.assertIn('authentication_error',r);client.call.assert_not_called()
    def test_mismatched_quote_does_not_count_as_success(self):
        client=self.client()
        client.call=Mock(side_effect=[self.response({'rt_cd':'0','output':{'stck_shrn_iscd':'000660','eps':'100'}}),self.response({'rt_cd':'0','output':[]})])
        r=run_probe(client,'005930',pause=Mock())
        self.assertFalse(r['results'][0]['success']);self.assertTrue(r['results'][1]['success'])
        self.assertEqual(r['results'][1]['annual_eps'],[])
    def test_panel_can_run_with_only_demo_pair_and_exports_redacted_result(self):
        import ast,os
        from pathlib import Path
        st=MagicMock();st.secrets={'KIS_ENV':'demo','KIS_APP_KEY':'PRIVATE_KEY','KIS_APP_SECRET':'PRIVATE_SECRET'}
        st.session_state={};st.text_input.return_value='005930';st.button.return_value=True
        result={'mode':'demo','code':'005930','fetched_at':'2026-10-15','results':[]}
        run=Mock(return_value=result)
        ns={'st':st,'os':os,'json':json,'probe_demo_keys':demo_keys,'DemoPublicProbe':DemoPublicProbe,'run_kis_probe':run,'BrokerError':BrokerError}
        node=next(n for n in ast.parse(Path('app.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='kis_demo_financial_probe_panel')
        exec(compile(ast.Module(body=[node],type_ignores=[]),'app.py','exec'),ns)
        ns['kis_demo_financial_probe_panel']()
        run.assert_called_once()
        self.assertEqual(json.loads(st.download_button.call_args.args[1]),result)
        self.assertFalse(st.button.call_args.kwargs['disabled'])
