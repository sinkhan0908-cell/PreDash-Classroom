import unittest,json,base64,types,ast
from copy import deepcopy
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import Mock,patch,MagicMock
import sys
try: import requests
except ImportError: sys.modules['requests']=types.SimpleNamespace(RequestException=Exception,request=None)
import predash.cloud_store as mod
from predash.cloud_store import CloudStore,StorageError,StorageConflict,watch_from_payload

class TransportError(Exception):pass

class CloudTests(unittest.TestCase):
    def setUp(self):
        self.store=CloudStore('https://testproject.supabase.co','sb_secret_PRIVATE')
        self.row={'id':'personal','version':0,'payload':{'stocks':[],'journal':[{'note':'keep'}],'runs':[{'id':1}],'unknown':'preserve'}}
    def test_url_and_key_validation_no_public_or_redirect_destination(self):
        for url in ['http://testproject.supabase.co','https://testproject.supabase.co.evil.com','https://user:pass@testproject.supabase.co','https://testproject.supabase.co/path','https://127.0.0.1','https://testproject.supabase.co?x=y']:
            with self.assertRaises(StorageError):CloudStore(url,'sb_secret_PRIVATE')
        with self.assertRaises(StorageError):CloudStore('https://testproject.supabase.co','sb_publishable_x')
        key='e30.'+base64.urlsafe_b64encode(json.dumps({'role':'service_role'}).encode()).decode().rstrip('=')+'.sig'
        self.assertEqual(CloudStore('https://testproject.supabase.co',key).headers['Authorization'],'Bearer '+key)
        self.assertNotIn('Authorization',self.store.headers)
    def test_read_and_compare_and_swap_preserve_other_data(self):
        self.row['payload']['stocks']=[{'code':'005930','name':'삼성전자','custom':'keep'}]
        response=deepcopy(self.row);response['version']=1
        response['payload']['stocks'][0]['name']='삼성'
        self.store.request=Mock(side_effect=[[self.row],[response]])
        saved=self.store.save_watch(self.row,['005930'],{'005930':'삼성'})
        self.assertEqual(saved['version'],1)
        request=self.store.request.call_args
        self.assertEqual(request.args[0],'PATCH')
        self.assertEqual(request.kwargs['params']['version'],'eq.0')
        self.assertEqual(request.kwargs['json']['payload']['journal'],self.row['payload']['journal'])
        self.assertEqual(request.kwargs['json']['payload']['stocks'][0]['custom'],'keep')
    def test_stale_and_racing_saves_do_not_overwrite(self):
        latest={**self.row,'version':2}
        self.store.request=Mock(return_value=[latest])
        with self.assertRaises(StorageConflict):self.store.save_watch(self.row,['005930'],{})
        self.assertEqual(self.store.request.call_count,1)
        self.store.request=Mock(side_effect=[[self.row],[]])
        with self.assertRaises(StorageConflict):self.store.save_watch(self.row,[],{})
    def test_missing_or_invalid_row_stops_no_implicit_create(self):
        for response in [[],[{'id':'personal','version':'0','payload':{}}],[{**self.row,'payload':{'stocks':[{'ticker':'005930'}]}}]]:
            self.store.request=Mock(return_value=response)
            with self.assertRaises(StorageError):self.store.load()
            self.assertEqual(self.store.request.call_count,1)
    def test_network_and_http_errors_do_not_leak_keys(self):
        for status in [401,403,404,500,302]:
            requests=types.SimpleNamespace(RequestException=TransportError,request=Mock(return_value=types.SimpleNamespace(status_code=status)))
            with patch.object(mod,'requests',requests):
                with self.assertRaises(StorageError) as exc:self.store.load()
                self.assertNotIn('PRIVATE',str(exc.exception))
                self.assertFalse(requests.request.call_args.kwargs['allow_redirects'])
    def test_ui_bootstrap_empty_cloud_keeps_unsaved_local_and_login_guard(self):
        st=MagicMock();st.session_state={'authorized':True,'watch_codes':['005930']};st.query_params={};st.secrets={}
        store=Mock();store.load.return_value=self.row
        ns={'st':st,'cloud_client':Mock(return_value=(store,'identity')),'watch_from_cloud':watch_from_payload,
            'clean_codes':lambda values:list(dict.fromkeys(c for c in values if c)),'datetime':datetime,'ZoneInfo':ZoneInfo,'StorageError':StorageError}
        tree=ast.parse(Path('app.py').read_text())
        for name in ('cloud_apply','cloud_bootstrap'):
            node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
            exec(compile(ast.Module(body=[node],type_ignores=[]),'app.py','exec'),ns)
        ns['cloud_bootstrap']();ns['cloud_bootstrap']()
        self.assertEqual(store.load.call_count,1)
        self.assertEqual(st.session_state['watch_codes'],['005930'])
        self.assertTrue(st.session_state['_cloud_dirty'])
        store.save_watch.assert_not_called()
        ns['cloud_apply'](self.row,force=True)
        self.assertEqual(st.session_state['watch_codes'],[])
    def test_failed_save_keeps_local_and_marks_unconfirmed(self):
        st=MagicMock();st.session_state={'watch_codes':['005930'],'_cloud_snapshot':self.row}
        store=Mock();store.save_watch.side_effect=StorageConflict('다른 기기 변경')
        ns={'st':st,'cloud_client':lambda:(store,'identity'),'StorageError':StorageError,'datetime':datetime,'ZoneInfo':ZoneInfo}
        node=next(n for n in ast.parse(Path('app.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='cloud_save_current')
        exec(compile(ast.Module(body=[node],type_ignores=[]),'app.py','exec'),ns)
        ns['cloud_save_current'](['005930'],{})
        self.assertTrue(st.session_state['_cloud_dirty'])
        self.assertEqual(st.session_state['watch_codes'],['005930'])
        self.assertIn('다른 기기',st.session_state['_cloud_error'])
    def test_cloud_client_requires_password_and_authorized_session(self):
        import hashlib,os
        st=MagicMock();st.secrets={'SUPABASE_URL':'https://testproject.supabase.co','SUPABASE_SECRET_KEY':'sb_secret_PRIVATE'}
        factory=Mock()
        ns=dict(st=st,os=os,password='',StorageError=StorageError,CloudStore=factory,cloud_settings=mod.settings,hashlib=hashlib)
        node=next(n for n in ast.parse(Path('app.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='cloud_client')
        exec(compile(ast.Module(body=[node],type_ignores=[]),'app.py','exec'),ns)
        for password,authorized in [('',True),('configured',False)]:
            ns['password']=password;st.session_state={'authorized':authorized}
            with self.assertRaises(StorageError):ns['cloud_client']()
        factory.assert_not_called()
    def test_save_from_one_client_can_be_read_by_another(self):
        database=deepcopy(self.row)
        def transport(method,url,**kw):
            nonlocal database
            if method=='PATCH':
                self.assertEqual(kw['params']['version'],'eq.'+str(database['version']))
                database={**database,**deepcopy(kw['json'])}
            return types.SimpleNamespace(status_code=200,json=lambda:[deepcopy(database)])
        fake=types.SimpleNamespace(RequestException=TransportError,request=Mock(side_effect=transport))
        with patch.object(mod,'requests',fake):
            first=self.store.load()
            self.store.save_watch(first,['005930'],{'005930':'삼성전자'})
            second=CloudStore('https://testproject.supabase.co','sb_secret_PRIVATE').load()
        self.assertEqual(watch_from_payload(second['payload']),(['005930'],{'005930':'삼성전자'}))
        self.assertEqual(second['payload']['journal'],self.row['payload']['journal'])
