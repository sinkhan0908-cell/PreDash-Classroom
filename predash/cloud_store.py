"""Backend-only personal watchlist persistence using the classroom SQL schema."""
import base64
import json
import re
from copy import deepcopy
from urllib.parse import urlsplit
import requests
from predash.watchlist import clean_codes,clean_names

class StorageError(RuntimeError):pass
class StorageConflict(StorageError):pass


def settings(values):
    url=str(values.get('SUPABASE_URL','')).strip().rstrip('/')
    modern=str(values.get('SUPABASE_SECRET_KEY','')).strip()
    legacy=str(values.get('SUPABASE_SERVICE_ROLE_KEY','')).strip()
    return url,modern or legacy


def stocks_payload(codes,names):
    codes=clean_codes(codes);names=clean_names(names,codes)
    return [{'code':c,'name':names.get(c,c)} for c in codes]


def watch_from_payload(payload):
    stocks=payload.get('stocks')
    if not isinstance(stocks,list):raise StorageError('저장된 stocks 배열 형식을 확인하세요.')
    codes=[];names={}
    for stock in stocks:
        if not isinstance(stock,dict) or not isinstance(stock.get('code'),str) or not re.fullmatch(r'\d{6}',stock.get('code','')):
            raise StorageError('클라우드 종목 형식이 현재 앱과 다릅니다. 원본을 보존하고 불러오기를 중단합니다.')
        code=stock['code']
        if code not in codes:codes.append(code)
        if isinstance(stock.get('name'),str):names[code]=stock['name']
    if len(codes)>8:raise StorageError('클라우드 종목이 현재 앱의 8개 한도를 넘습니다. 자동으로 잘라 저장하지 않습니다.')
    return codes,clean_names(names,codes)


class CloudStore:
    def __init__(self,url,key):
        parsed=urlsplit(url)
        if (parsed.scheme!='https' or not re.fullmatch(r'[a-z0-9-]+\.supabase\.co',parsed.netloc)
                or parsed.path or parsed.query or parsed.fragment):
            raise StorageError('SUPABASE_URL은 https://프로젝트.supabase.co 형식이어야 합니다.')
        self.url=url+'/rest/v1/stock_dash_state'
        self.headers={'apikey':key,'Content-Type':'application/json'}
        if key.startswith('sb_secret_'):
            pass # New secret keys are API keys, not JWT bearer tokens.
        else:
            try:
                part=key.split('.')[1]
                role=json.loads(base64.urlsafe_b64decode(part+'='*(-len(part)%4)))['role']
            except (ValueError,IndexError,KeyError,TypeError):role=None
            if role!='service_role':raise StorageError('서버용 Secret key 또는 legacy service_role 키가 필요합니다. anon·publishable 키는 사용할 수 없습니다.')
            self.headers['Authorization']='Bearer '+key

    def request(self,method,extra_headers=None,**kwargs):
        try:
            response=requests.request(method,self.url,headers={**self.headers,**(extra_headers or {})},timeout=(5,15),allow_redirects=False,**kwargs)
            if not 200<=response.status_code<300:
                hints={401:'URL과 서버 키가 같은 프로젝트인지 확인하세요.',403:'테이블의 service_role 권한을 확인하세요.',404:'SQL 실행 및 stock_dash_state 테이블을 확인하세요.'}
                raise StorageError(f'Supabase HTTP {response.status_code} · '+hints.get(response.status_code,'저장소 응답을 확인하세요.'))
            data=response.json()
            if not isinstance(data,list):raise ValueError
            return data
        except (requests.RequestException,ValueError):
            raise StorageError('Supabase 통신·응답 확인 실패. 저장 요청이었다면 반영 여부를 다시 불러와 확인하세요.') from None

    def load(self):
        rows=self.request('GET',params={'id':'eq.personal','select':'id,version,payload','limit':'1'})
        if len(rows)!=1:raise StorageError('personal 행이 없습니다. schema.sql을 실행하세요.')
        row=rows[0]
        if (row.get('id')!='personal' or type(row.get('version')) is not int or row['version']<0 or not isinstance(row.get('payload'),dict)):
            raise StorageError('저장소의 version·payload 구조를 확인하세요.')
        watch_from_payload(row['payload'])
        return deepcopy(row)

    def save_watch(self,snapshot,codes,names):
        latest=self.load()
        if latest['version']!=snapshot['version']:
            raise StorageConflict('다른 기기에서 자료가 변경됐습니다. 클라우드를 다시 불러온 뒤 수정해 주세요. 현재 목록은 화면에 유지합니다.')
        payload=deepcopy(latest['payload'])
        original={r['code']:r for r in payload['stocks']}
        payload['stocks']=[{**original.get(r['code'],{}),**r} for r in stocks_payload(codes,names)]
        version=latest['version']+1
        rows=self.request('PATCH',extra_headers={'Prefer':'return=representation'},params={'id':'eq.personal','version':'eq.'+str(latest['version'])},json={'payload':payload,'version':version})
        if not rows:raise StorageConflict('동시 저장 충돌이 발생했습니다. 현재 목록을 유지합니다. 클라우드 다시 불러오기가 필요합니다.')
        if len(rows)!=1 or rows[0].get('id')!='personal' or rows[0].get('version')!=version or rows[0].get('payload')!=payload:
            raise StorageError('저장 응답이 요청과 일치하지 않습니다. 클라우드를 다시 불러와 확인하세요.')
        return deepcopy(rows[0])
