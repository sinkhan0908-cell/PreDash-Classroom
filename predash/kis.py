"""Read-only KIS domestic-stock balance adapter. No order endpoints."""
from __future__ import annotations
import os
import re
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import requests

class BrokerError(RuntimeError):
    pass

def account_settings(mode=None):
    """An explicit demo request never falls back to real credentials."""
    selected=mode or os.getenv('KIS_ENV','demo').strip()
    prefix='KIS_'
    if mode=='demo':
        demo_keys=('KIS_DEMO_APP_KEY','KIS_DEMO_APP_SECRET','KIS_DEMO_CANO','KIS_DEMO_ACNT_PRDT_CD')
        if any(os.getenv(key,'').strip() for key in demo_keys) or os.getenv('KIS_ENV','demo').strip()!='demo':
            prefix='KIS_DEMO_'
    return {'mode':selected,'key':os.getenv(prefix+'APP_KEY','').strip(),
            'secret':os.getenv(prefix+'APP_SECRET','').strip(),'cano':os.getenv(prefix+'CANO','').strip(),
            'product':os.getenv(prefix+'ACNT_PRDT_CD','').strip()}

def number(value):
    try:
        result = float(str(value).replace(',', ''))
        if result != result or abs(result) == float('inf'):
            raise ValueError
        return result
    except (ValueError, TypeError):
        raise BrokerError('잔고 응답의 숫자를 확인할 수 없습니다.') from None

class KIS:
    def __init__(self, mode=None, *, settings=None):
        settings=account_settings(mode) if settings is None else settings
        self.key,self.secret,self.cano,self.product,self.mode=(settings[k] for k in ('key','secret','cano','product','mode'))
        if not self.key or not self.secret or not re.fullmatch(r'\d{8}', self.cano) or not re.fullmatch(r'\d{2}', self.product):
            raise BrokerError('한국투자증권 키와 계좌번호 앞 8자리·뒤 2자리를 설정하세요.')
        if self.mode not in ('real', 'demo'):
            raise BrokerError('KIS_ENV는 real 또는 demo입니다.')
        self.base = 'https://openapi.koreainvestment.com:9443' if self.mode == 'real' else 'https://openapivts.koreainvestment.com:29443'
        self.token = None
        self.expires = 0

    def call(self, method, path, **kwargs):
        try:
            response = requests.request(method, self.base + path, timeout=(5, 20), **kwargs)
            if response.status_code in (401,403):
                raise BrokerError(f'증권사 인증 거부 (HTTP {response.status_code}) · KIS_ENV의 실전/모의 구분과 해당 환경의 키를 확인하세요.')
            if response.status_code == 429:
                raise BrokerError('증권사 호출 제한 (HTTP 429) · 잠시 후 다시 시도하세요.')
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError
            return response, data
        except (requests.RequestException, ValueError):
            raise BrokerError('증권사 연결 실패 · 키, 환경, 서비스 상태를 확인하세요.') from None

    @staticmethod
    def result_error(data, context):
        """Expose only a bounded provider code, never raw broker messages/account data."""
        code=str(data.get('msg_cd',''))
        safe=code if re.fullmatch(r'[A-Z0-9]{3,16}',code) else '미확인'
        if safe=='OPSQ2000':
            return BrokerError(f'{context} (OPSQ2000 · 계좌번호 검사 실패) · KIS Developers에서 이 앱 키를 발급한 실전/모의 계좌와 Secrets의 앞 8자리·뒤 2자리, KIS_ENV가 일치하는지 확인하세요.')
        return BrokerError(f'{context} (증권사 코드 {safe}) · 실전/모의 키, 계좌 구분, 조회 권한을 확인하세요.')

    def authorize(self):
        if self.token and time.time() < self.expires:
            return
        _, data = self.call('POST', '/oauth2/tokenP', json={'grant_type':'client_credentials', 'appkey':self.key, 'appsecret':self.secret})
        if not data.get('access_token'):
            raise self.result_error(data,'증권사 토큰 발급 실패')
        self.token = data['access_token']
        self.expires = time.time() + max(0, number(data.get('expires_in', 0)) - 120)

    def balance(self):
        self.authorize()
        rows, summary, seen = [], {}, set()
        fk = nk = cont = ''
        for _ in range(100):
            response, data = self.call('GET', '/uapi/domestic-stock/v1/trading/inquire-balance',
                headers={'authorization':'Bearer '+self.token, 'appkey':self.key, 'appsecret':self.secret,
                         'tr_id':'TTTC8434R' if self.mode=='real' else 'VTTC8434R', 'custtype':'P', 'tr_cont':cont},
                params={'CANO':self.cano, 'ACNT_PRDT_CD':self.product, 'AFHR_FLPR_YN':'N', 'OFL_YN':'',
                        'INQR_DVSN':'02', 'UNPR_DVSN':'01', 'FUND_STTL_ICLD_YN':'N',
                        'FNCG_AMT_AUTO_RDPT_YN':'N', 'PRCS_DVSN':'00', 'CTX_AREA_FK100':fk, 'CTX_AREA_NK100':nk})
            if str(data.get('rt_cd')) != '0' or not isinstance(data.get('output1'), list) or not isinstance(data.get('output2'), list):
                raise self.result_error(data,'잔고 조회 실패 · 일부 결과는 표시하지 않습니다.')
            rows.extend(data['output1'])
            if data['output2'] and not summary:
                summary = data['output2'][0]
            if response.headers.get('tr_cont') not in ('F','M'):
                break
            fk,nk=str(data.get('ctx_area_fk100','')).strip(),str(data.get('ctx_area_nk100','')).strip()
            if not nk or (fk,nk) in seen:
                raise BrokerError('잔고 다음 페이지를 확인하지 못했습니다.')
            seen.add((fk,nk)); cont='N'; time.sleep(0.6)
        else:
            raise BrokerError('잔고 조회 페이지 한도를 초과했습니다.')
        positions=[]; codes=set()
        for row in rows:
            qty=number(row.get('hldg_qty'))
            if qty<=0: continue
            code=str(row.get('pdno',''))
            if code in codes: raise BrokerError('중복 종목 응답 · 전체 조회를 중단했습니다.')
            codes.add(code)
            positions.append({'code':code,'name':row.get('prdt_name',code),'quantity':qty,
                'average_cost':number(row.get('pchs_avg_pric')),'price':number(row.get('prpr')),
                'value':number(row.get('evlu_amt')),'pnl':number(row.get('evlu_pfls_amt'))})
        total=sum(p['value'] for p in positions)
        for p in positions: p['weight']=p['value']/total*100 if total>0 else 0
        return {'positions':positions,'value':total,'pnl':sum(p['pnl'] for p in positions),
                'cash':number(summary['dnca_tot_amt']) if summary.get('dnca_tot_amt') not in (None,'') else None,
                'mode':self.mode,'fetched':datetime.now(ZoneInfo('Asia/Seoul')).isoformat()}

    def investor_flow(self,code):
        """KIS daily investor net-buy quantities; exchange session, not live flow."""
        if not re.fullmatch(r'[0-9]{6}',code):raise BrokerError('수급 종목코드를 확인하세요.')
        self.authorize()
        _,data=self.call('GET','/uapi/domestic-stock/v1/quotations/inquire-investor',
            headers={'authorization':'Bearer '+self.token,'appkey':self.key,'appsecret':self.secret,
                     'tr_id':'FHKST01010900','custtype':'P'},
            params={'FID_COND_MRKT_DIV_CODE':'J','FID_INPUT_ISCD':code})
        if str(data.get('rt_cd'))!='0' or not isinstance(data.get('output'),list):
            raise self.result_error(data,'투자자별 수급 조회 실패')
        from predash.flow import summarize_flow
        return summarize_flow(data['output'],datetime.now(ZoneInfo('Asia/Seoul')).date())

    def fills(self, days=30):
        """Read completed domestic-stock orders within recent 3 months; never submit orders."""
        if not isinstance(days,int) or not 1<=days<=90:
            raise BrokerError('조회기간은 1~90일 사이로 선택하세요.')
        self.authorize()
        end=datetime.now(ZoneInfo('Asia/Seoul')).date()
        start=end-timedelta(days=days-1)
        rows=[];fk=nk=cont='';seen=set()
        for _ in range(100):
            response,data=self.call('GET','/uapi/domestic-stock/v1/trading/inquire-daily-ccld',
                headers={'authorization':'Bearer '+self.token,'appkey':self.key,'appsecret':self.secret,
                         'tr_id':'TTTC0081R' if self.mode=='real' else 'VTTC0081R','custtype':'P','tr_cont':cont},
                params={'CANO':self.cano,'ACNT_PRDT_CD':self.product,
                        'INQR_STRT_DT':start.strftime('%Y%m%d'),'INQR_END_DT':end.strftime('%Y%m%d'),
                        'SLL_BUY_DVSN_CD':'00','PDNO':'','CCLD_DVSN':'01','INQR_DVSN':'01',
                        'INQR_DVSN_3':'00','ORD_GNO_BRNO':'','ODNO':'','INQR_DVSN_1':'',
                        'CTX_AREA_FK100':fk,'CTX_AREA_NK100':nk})
            if str(data.get('rt_cd'))!='0' or not isinstance(data.get('output1'),list):
                raise self.result_error(data,'체결 내역 조회 실패 · 일부 기록은 분석하지 않습니다.')
            rows.extend(data['output1'])
            if response.headers.get('tr_cont') not in ('F','M'):
                break
            fk,nk=str(data.get('ctx_area_fk100','')).strip(),str(data.get('ctx_area_nk100','')).strip()
            if not nk or (fk,nk) in seen:
                raise BrokerError('체결 내역 다음 페이지를 확인하지 못했습니다.')
            seen.add((fk,nk));cont='N';time.sleep(0.6)
        else:
            raise BrokerError('체결 내역 조회 페이지 한도를 초과했습니다.')
        return {'rows':rows,'from':start.isoformat(),'to':end.isoformat(),
                'fetched':datetime.now(ZoneInfo('Asia/Seoul')).isoformat()}

    def market_flow(self,code,as_of=None):
        """Read daily market investor flows; no account/order parameters."""
        if code not in ('0001','1001'):raise BrokerError('지원하지 않는 시장입니다.')
        end=as_of or datetime.now(ZoneInfo('Asia/Seoul')).date()
        if not isinstance(end,date):raise BrokerError('수급 기준일을 확인하세요.')
        self.authorize()
        _,data=self.call('GET','/uapi/domestic-stock/v1/quotations/inquire-investor-daily-by-market',
            headers={'authorization':'Bearer '+self.token,'appkey':self.key,'appsecret':self.secret,
                     'tr_id':'FHPTJ04040000','custtype':'P'},
            params={'FID_COND_MRKT_DIV_CODE':'U','FID_INPUT_ISCD':code,
                    'FID_INPUT_DATE_1':end.strftime('%Y%m%d'),'FID_INPUT_DATE_2':end.strftime('%Y%m%d'),
                    'FID_INPUT_ISCD_1':'KSP' if code=='0001' else 'KSQ','FID_INPUT_ISCD_2':code})
        if str(data.get('rt_cd'))!='0' or not isinstance(data.get('output'),list):
            raise self.result_error(data,'시장 수급 조회 실패')
        from predash.market import market_flow,MarketDataError
        try:return market_flow(data['output'],end)
        except MarketDataError as exc:raise BrokerError(str(exc)) from None

    def daily_bars(self, code, end_day):
        """Original daily prices strictly before a purchase, with a bounded lookback."""
        if not re.fullmatch(r'\d{6}', code):
            raise BrokerError('일별 시세를 조회할 종목코드가 올바르지 않습니다.')
        if not isinstance(end_day, date):
            raise BrokerError('매수일을 확인할 수 없습니다.')
        self.authorize()
        yesterday=end_day-timedelta(days=1)
        start=yesterday-timedelta(days=49)
        _,data=self.call('GET','/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice',
            headers={'authorization':'Bearer '+self.token,'appkey':self.key,'appsecret':self.secret,
                     'tr_id':'FHKST03010100','custtype':'P'},
            params={'FID_COND_MRKT_DIV_CODE':'J','FID_INPUT_ISCD':code,
                    'FID_INPUT_DATE_1':start.strftime('%Y%m%d'),
                    'FID_INPUT_DATE_2':yesterday.strftime('%Y%m%d'),
                    'FID_PERIOD_DIV_CODE':'D','FID_ORG_ADJ_PRC':'1'})
        if str(data.get('rt_cd'))!='0' or not isinstance(data.get('output2'),list):
            raise BrokerError('당시 일별 시세를 확인하지 못했습니다.')
        return data['output2']

    def price_history(self, code, as_of):
        """Return KIS daily closes in the same row shape as public stock data."""
        if not re.fullmatch(r'\d{6}', code):
            raise BrokerError('일별 시세를 조회할 종목코드가 올바르지 않습니다.')
        if not isinstance(as_of, date):
            raise BrokerError('시세 기준일을 확인할 수 없습니다.')
        self.authorize()
        start=as_of-timedelta(days=90)
        _,data=self.call('GET','/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice',
            headers={'authorization':'Bearer '+self.token,'appkey':self.key,'appsecret':self.secret,
                     'tr_id':'FHKST03010100','custtype':'P'},
            params={'FID_COND_MRKT_DIV_CODE':'J','FID_INPUT_ISCD':code,
                    'FID_INPUT_DATE_1':start.strftime('%Y%m%d'),
                    'FID_INPUT_DATE_2':as_of.strftime('%Y%m%d'),
                    'FID_PERIOD_DIV_CODE':'D','FID_ORG_ADJ_PRC':'1'})
        if str(data.get('rt_cd'))!='0' or not isinstance(data.get('output2'),list):
            raise self.result_error(data,'KIS 일별 종가 조회 실패')
        rows=[]
        for row in data['output2']:
            day=str(row.get('stck_bsop_date','')).strip()
            close=str(row.get('stck_clpr','')).strip()
            if re.fullmatch(r'\d{8}',day) and close:
                rows.append({'srtnCd':code,'basDt':day,'clpr':close,
                             'itmsNm':row.get('hts_kor_isnm') or ''})
        if not rows:
            raise BrokerError('KIS 일별 종가 자료가 없습니다.')
        return rows

    def index_bars(self, code, as_of=None):
        """KOSPI/KOSDAQ daily index observations; read-only quotation endpoint."""
        if code not in ('0001','1001'):
            raise BrokerError('지원하지 않는 지수입니다.')
        self.authorize()
        end=as_of or datetime.now(ZoneInfo('Asia/Seoul')).date()
        if not isinstance(end,date): raise BrokerError('지수 기준일이 올바르지 않습니다.')
        start=end-timedelta(days=49)
        _,data=self.call('GET','/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice',
            headers={'authorization':'Bearer '+self.token,'appkey':self.key,'appsecret':self.secret,
                     'tr_id':'FHKUP03500100','custtype':'P'},
            params={'FID_COND_MRKT_DIV_CODE':'U','FID_INPUT_ISCD':code,
                    'FID_INPUT_DATE_1':start.strftime('%Y%m%d'),
                    'FID_INPUT_DATE_2':end.strftime('%Y%m%d'),
                    'FID_PERIOD_DIV_CODE':'D'})
        if str(data.get('rt_cd'))!='0' or not isinstance(data.get('output2'),list):
            raise BrokerError('지수 일별 시세를 확인하지 못했습니다.')
        return data['output2']

