"""User-triggered demo-only public-data diagnostics; no accounts or orders."""
import math
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from predash.kis import KIS, BrokerError

PRICE = '/uapi/domestic-stock/v1/quotations/inquire-price'
RATIOS = '/uapi/domestic-stock/v1/finance/financial-ratio'


def demo_keys(session, secrets):
    """Complete key pair from one source, no real credentials or account requirement."""
    if session.get('mode') == 'demo' and all(session.get(k) for k in ('key','secret')):
        return {k:str(session[k]).strip() for k in ('key','secret')}
    dedicated = any(secrets.get(k) for k in ('KIS_DEMO_APP_KEY','KIS_DEMO_APP_SECRET'))
    prefix = 'KIS_DEMO_' if dedicated or str(secrets.get('KIS_ENV','demo')).strip()!='demo' else 'KIS_'
    pair = {'key':str(secrets.get(prefix+'APP_KEY','')).strip(),'secret':str(secrets.get(prefix+'APP_SECRET','')).strip()}
    return pair if all(pair.values()) else {'key':'','secret':''}


class DemoPublicProbe(KIS):
    def __init__(self, keys):
        self.mode='demo'
        self.base='https://openapivts.koreainvestment.com:29443'
        self.key,self.secret=keys['key'],keys['secret']
        if not self.key or not self.secret: raise BrokerError('모의투자 App Key·Secret 설정이 필요합니다.')
        self.cano=self.product=''
        self.token=None
        self.expires=0

    def call(self, method, path, **kwargs):
        if (method,path) not in {('POST','/oauth2/tokenP'),('GET',PRICE),('GET',RATIOS)}:
            raise BrokerError('이 테스트는 모의 환경의 공개 시세·재무 조회만 허용합니다.')
        return super().call(method,path,**kwargs)


def numeric(value):
    try:
        result=float(str(value).replace(',',''))
        return result if math.isfinite(result) else None
    except (ValueError,TypeError): return None


def safe_code(value):
    text=str(value) if value is not None else ''
    return text if re.fullmatch(r'[A-Z0-9_-]{1,24}',text) else None


def run_probe(client, code, pause=time.sleep):
    if client.mode!='demo' or client.base!='https://openapivts.koreainvestment.com:29443':
        raise BrokerError('모의투자 환경에서만 테스트할 수 있습니다.')
    if not re.fullmatch(r'\d{6}',code): raise BrokerError('종목코드는 숫자 6자리여야 합니다.')
    result={'mode':'demo','code':code,'fetched_at':datetime.now(ZoneInfo('Asia/Seoul')).isoformat(timespec='seconds'),'results':[]}
    try:
        client.authorize()
    except BrokerError as exc:
        # KIS adapter errors are bounded/redacted; never include provider msg1/body.
        result['authentication_error']=str(exc)
        return result
    headers={'authorization':'Bearer '+client.token,'appkey':client.key,'appsecret':client.secret,'custtype':'P'}
    for i,(label,path,tr) in enumerate([('현재가 EPS·PER',PRICE,'FHKST01010100'),('연간 EPS 재무비율',RATIOS,'FHKST66430300')]):
        if i: pause(1.1)
        params={'FID_COND_MRKT_DIV_CODE':'J','FID_INPUT_ISCD':code}
        if path==RATIOS:params['FID_DIV_CLS_CODE']='0'
        item={'api':label,'path':path,'success':False,'status_code':None,'message_code':None,'values':{},'annual_eps':[]}
        try:
            response,data=client.call('GET',path,headers={**headers,'tr_id':tr},params=params)
            item.update(status_code=safe_code(data.get('rt_cd')),message_code=safe_code(data.get('msg_cd')))
            if str(data.get('rt_cd'))!='0':
                item['reason']='API 응답 실패 · 모의 지원·권한·환경 확인 필요. 오류코드만으로 미지원 확정하지 않습니다.'
            elif path==PRICE:
                output=data.get('output')
                if not isinstance(output,dict):raise BrokerError('현재가 응답 구조 확인 필요')
                returned=str(output.get('stck_shrn_iscd',''))
                if returned and returned!=code:raise BrokerError('응답 종목코드 불일치')
                item['success']=True
                item['values']={key:numeric(output.get(key)) for key in ('stck_prpr','eps','per')}
                item['reason']='API 성공 · EPS 대상 연도·회계 기준은 이 응답만으로 확정하지 않습니다.'
            else:
                output=data.get('output')
                if isinstance(output,dict):output=[output]
                if not isinstance(output,list) or any(not isinstance(row,dict) for row in output):raise BrokerError('재무비율 응답 구조 확인 필요')
                seen=set()
                for row in output[:100]:
                    period=str(row.get('stac_yymm',''))
                    eps=numeric(row.get('eps'))
                    if re.fullmatch(r'\d{4}(0[1-9]|1[0-2])',period) and period not in seen:
                        item['annual_eps'].append({'period':period,'eps':eps})
                        seen.add(period)
                item['annual_eps'].sort(key=lambda r:r['period'])
                item['success']=True
                item['more_pages']=str(response.headers.get('tr_cont','')).upper() in ('M','F')
                item['reason']='API 성공 · 최초 응답만 검사. 5년 연속성·결산월·회계 기준·EPS 정의는 추가 검증 필요.'
                if not item['annual_eps']:item['reason']='API 성공이지만 유효한 결산 년월·EPS 자료를 확인하지 못했습니다.'
        except BrokerError as exc:
            item['reason']=str(exc)
        result['results'].append(item)
    return result
