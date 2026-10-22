"""Load one compatible Lynch module generation before binding app callables."""
import importlib
from threading import RLock

_LOCK=RLock()
# Collector revision is separate from the persisted financial-data schema version.
SPECS=(
    ('predash.ttm','COLLECTOR_VERSION',3),
    ('predash.pharma_ir','PARSER_VERSION',2),
    ('predash.dart_xbrl','READER_VERSION',4),
    ('predash.dart_network','DIAGNOSTIC_VERSION',1),
    ('predash.valuation_inputs','INPUTS_VERSION',2),
    ('predash.valuation_evidence','VALUATION_VERSION',3),
)


def ensure_lynch_runtime(importer=None,reloader=None):
    importer=importer or importlib.import_module
    reloader=reloader or importlib.reload
    loaded={};parent_reloaded=False
    with _LOCK:
        for name,field,required in SPECS:
            module=importer(name)
            changed=getattr(module,field,0)<required or parent_reloaded
            if changed:
                module=reloader(module)
                if name=='predash.ttm':parent_reloaded=True
            if getattr(module,field,0)<required:
                raise RuntimeError('린치 실행 파일 버전이 최신 배포와 다릅니다. 앱 서버 재시작·배포 상태를 확인해 주세요: '+name)
            loaded[name]=module
    # Reload dependants when ttm changes so their imported exception classes and
    # calculation functions refer to the same generation as the app bindings.
    return loaded


def runtime_versions():
    return {name.rsplit('.',1)[-1]:getattr(importlib.import_module(name),field,0)
            for name,field,_ in SPECS}
