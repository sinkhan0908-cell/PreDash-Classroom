import types,unittest
from unittest.mock import Mock,MagicMock
from predash.runtime import ensure_lynch_runtime,SPECS,runtime_versions

class RuntimeGenerationTests(unittest.TestCase):
    def modules(self):return {name:types.SimpleNamespace(**{field:version}) for name,field,version in SPECS}
    def test_current_generation_is_not_reloaded_on_each_rerun(self):
        modules=self.modules();reload=Mock()
        result=ensure_lynch_runtime(importer=modules.__getitem__,reloader=reload)
        self.assertEqual(result,modules);reload.assert_not_called()
    def test_old_collector_reloads_all_dependants_before_app_binds_aliases(self):
        modules=self.modules();modules['predash.ttm'].COLLECTOR_VERSION=0
        old_error=type('OldError',(ValueError,),{});new_error=type('NewError',(ValueError,),{})
        modules['predash.ttm'].TtmError=old_error;modules['predash.pharma_ir'].TtmError=old_error
        calls=[]
        def reload(module):
            name=next(k for k,v in modules.items() if v is module);calls.append(name)
            _,field,required=next(s for s in SPECS if s[0]==name)
            setattr(module,field,required)
            if name in ('predash.ttm','predash.pharma_ir'):module.TtmError=new_error
            return module
        result=ensure_lynch_runtime(importer=modules.__getitem__,reloader=reload)
        self.assertEqual(calls,[s[0] for s in SPECS])
        self.assertIs(result['predash.ttm'].TtmError,result['predash.pharma_ir'].TtmError)
    def test_old_parser_is_refreshed_even_when_collector_already_current(self):
        modules=self.modules();modules['predash.pharma_ir'].PARSER_VERSION=0
        def reload(module):module.PARSER_VERSION=2;return module
        result=ensure_lynch_runtime(importer=modules.__getitem__,reloader=Mock(side_effect=reload))
        self.assertEqual(result['predash.pharma_ir'].PARSER_VERSION,2)
    def test_old_disk_files_fail_explicitly_instead_of_claiming_latest_version(self):
        modules=self.modules();modules['predash.ttm'].COLLECTOR_VERSION=0
        with self.assertRaisesRegex(RuntimeError,'서버 재시작'):
            ensure_lynch_runtime(importer=modules.__getitem__,reloader=lambda m:m)
    def test_export_separates_runtime_versions_from_saved_source_generation(self):
        import json
        from tests_lynch_ui import functions
        st=MagicMock();st.session_state={}
        saved={'data':{'code':'214450'},'ttm':{'status':'failed'}}
        ns=functions(['lynch_options'],{'st':st,'json':json})
        ns['lynch_options']('214450',saved,{'per':None},'2026-10-20')
        payload=json.loads(st.download_button.call_args.args[1])
        self.assertEqual(payload['runtime_versions']['ttm'],3)
        self.assertEqual(payload['runtime_versions']['pharma_ir'],2)
        self.assertNotIn('collector_version',payload['evidence']['ttm'])
