"""Trailing common-basic EPS from matched cumulative profit and share-days.

No sum of rounded EPS, owner-wide profit substitution, forecasts, or KIS EPS mixing.
"""
import calendar
import hashlib
import io
import math
import re
from datetime import date,datetime,timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit,urljoin
from html.parser import HTMLParser
from predash.financial_validation import quote_date_check,numeric

VERSION=1
ROOT='https://images.samsung.com/is/content/samsung/assets/global/ir/docs/'
INDEX='https://www.samsung.com/global/ir/financial-information/audited-financial-statements/'

class TtmError(ValueError):pass
class MissingReport(TtmError):pass


def now():return datetime.now(ZoneInfo('Asia/Seoul')).isoformat(timespec='seconds')


def days(start,end):return (date.fromisoformat(end)-date.fromisoformat(start)).days+1


def calculate(block,quote,today):
    """Calculate again with the displayed price; preserve source facts and timestamps."""
    block=block if isinstance(block,dict) else {}
    source_inputs=block.get('inputs',[])
    if not isinstance(source_inputs,list) or any(not isinstance(r,dict) for r in source_inputs):source_inputs=[]
    result={'per':None,'eps':None,'period_start':None,'period_end':None,'profit':None,'weighted_shares':None,
        'method':'common_basic_share_days_v1','data_gaps':[],'source_inputs':source_inputs,
        'financial_fetched_at':block.get('fetched_at') if isinstance(block,dict) else None}
    try:
        if not isinstance(block,dict) or block.get('status')!='success' or block.get('version')!=VERSION:raise TtmError((block or {}).get('reason','TTM용 공식 자료 미수집'))
        rows=block['inputs']
        if not isinstance(rows,list) or any(not isinstance(r,dict) for r in rows) or len(rows) not in (1,3):raise TtmError('TTM 대상 기간 수 불일치')
        for r in rows:
            if r.get('basis')!='CFS' or r.get('definition')!='ordinary_basic' or r.get('currency')!='KRW':raise TtmError('연결·보통주·기본 EPS·통화 기준 불일치')
            if r.get('share_adjustment_flag'):raise TtmError('분할·소급 주식수 조정 대조 필요')
            for k in ('profit','weighted_shares','reported_eps'):
                if type(r.get(k)) not in (int,float) or not math.isfinite(r[k]):raise TtmError('순이익·가중평균 주식수·EPS 누락')
            if r['weighted_shares']<=0 or not isinstance(r.get('source'),str) or not r['source'].startswith('https://'):raise TtmError('주식수·출처 미확인')
            if abs(r['profit']/r['weighted_shares']-r['reported_eps'])>1.1:raise TtmError('순이익 ÷ 주식수와 공시 EPS 불일치')
            if date.fromisoformat(r['available_on'])>today or date.fromisoformat(r['period_end'])>today:raise TtmError('미공개 또는 미완료 기간')
            if days(r['period_start'],r['period_end'])<=0:raise TtmError('기간 역전')
        annual=rows[0]
        y=date.fromisoformat(annual['period_end']).year
        if annual['period_start']!=f'{y}-01-01' or annual['period_end']!=f'{y}-12-31':raise TtmError('12월 결산 연간 기간 미확인')
        profit=annual['profit'];share_days=annual['weighted_shares']*days(annual['period_start'],annual['period_end'])
        start=annual['period_start'];end=annual['period_end']
        if len(rows)==3:
            current,prior=rows[1:]
            if current['period_start']!=f'{y+1}-01-01' or prior['period_start']!=f'{y}-01-01':raise TtmError('누적 기간 시작 불일치')
            suffix=current['period_end'][4:]
            if suffix not in ('-03-31','-06-30','-09-30') or prior['period_end']!=str(y)+suffix or current['period_end']!=str(y+1)+suffix:raise TtmError('전년 동기 누적 기간 불일치')
            if current['source']!=prior['source'] or current.get('document_sha256')!=prior.get('document_sha256'):raise TtmError('전년 동기는 당기 보고서 비교값을 사용해야 합니다.')
            profit+=current['profit']-prior['profit']
            share_days+=current['weighted_shares']*days(current['period_start'],current['period_end'])-prior['weighted_shares']*days(prior['period_start'],prior['period_end'])
            start=(date.fromisoformat(prior['period_end'])+timedelta(days=1)).isoformat();end=current['period_end']
        length=days(start,end)
        if length not in (365,366) or share_days<=0:raise TtmError('12개월 기간·주식수 가중합 미확인')
        shares=share_days/length;eps=profit/shares
        if not all(math.isfinite(v) for v in (profit,shares,eps)):raise TtmError('TTM 계산 수치 범위 초과')
        result.update(eps=eps,profit=profit,weighted_shares=shares,period_start=start,period_end=end)
        gap,_=quote_date_check(today.isoformat(),quote.get('date'))
        if gap:raise TtmError(gap)
        closing=date.fromisoformat(quote['date'])
        if any(date.fromisoformat(r['available_on'])>closing for r in rows):raise TtmError('가격 기준일이 사용 보고서 확인 가능일 이전')
        if closing<date.fromisoformat(end):raise TtmError('가격이 TTM 기간 종료 이전')
        if type(quote.get('close')) not in (int,float) or not math.isfinite(quote['close']) or quote['close']<=0 or not quote.get('source'):raise TtmError('가격·출처 미확인')
        if eps<=0:raise TtmError('최근 12개월 보통주 이익이 0·적자여서 PER 미산출')
        result['per']=quote['close']/eps
        result['data_gaps'].append('공시의 반올림된 금액·주식수로 재구성한 참고 계산. 전체 주식 분할·재작성 이력 수동 대조는 미완료')
        if any(r.get('available_on_type')=='audit_review_report_date' for r in rows):result['data_gaps'].append('IR 보고서 작성일 사용 · 실제 최초 공시 시각 미대조. 과거 시점 투자 검증용으로 사용하지 않습니다.')
        if block.get('last_error'):result['data_gaps'].append('최근 TTM 확인 실패 · 이전 성공 원자료 사용: '+block['last_error'])
    except (TtmError,KeyError,TypeError,ValueError) as exc:
        result['data_gaps'].append(str(exc) if isinstance(exc,TtmError) else 'TTM 원자료 형식·날짜 확인 필요')
    return result


def due(block,at):
    if not isinstance(block,dict) or block.get('version')!=VERSION:return True
    try:
        age=(datetime.fromisoformat(at)-datetime.fromisoformat(block['last_attempt_at'])).total_seconds()
        return age<0 or age >= (900 if block.get('last_error') or block.get('status')!='success' else 21600)
    except (KeyError,TypeError,ValueError):return True


def download_pdf(url):
    """Only fixed public Samsung IR PDFs, bounded transfer, no credentials/redirects."""
    parts=urlsplit(url)
    if parts.scheme!='https' or parts.netloc!='images.samsung.com' or not re.fullmatch(r'/is/content/samsung/assets/global/ir/docs/20\d{2}_con_quarter0[1-4]_all\.pdf',parts.path) or parts.query or parts.fragment:
        raise TtmError('공식 IR PDF 주소 확인 필요')
    import requests
    try:
        with requests.get(url,timeout=(4,12),allow_redirects=False,stream=True) as r:
            if r.status_code==404:raise MissingReport('공식 보고서 미게시')
            if r.status_code!=200:raise TtmError('공식 IR PDF 응답 실패 · HTTP '+str(r.status_code))
            chunks=[];size=0
            for part in r.iter_content(65536):
                size+=len(part)
                if size>8000000:raise TtmError('공식 PDF 크기 한도 초과')
                chunks.append(part)
            body=b''.join(chunks)
            if not body.startswith(b'%PDF-'):raise TtmError('공식 IR 응답이 PDF가 아닙니다.')
            return body
    except requests.RequestException:raise TtmError('공식 IR PDF 연결 실패 · 이전 성공 자료 유지') from None


def pdf_text(body):
    try:
        from pypdf import PdfReader
        reader=PdfReader(io.BytesIO(body))
        if reader.is_encrypted or not 5<=len(reader.pages)<=250:raise TtmError('공식 PDF 페이지·암호화 확인 필요')
        return [p.extract_text() or '' for p in reader.pages]
    except ImportError:raise TtmError('PDF 읽기 모듈 준비 필요 · 앱 재시작 후 재시도') from None
    except TtmError:raise
    except Exception:raise TtmError('공식 PDF 텍스트 형식 확인 필요') from None


def parse_samsung(pages,year,quarter,url,digest,today):
    """A strict, source-specific EPS-note parser; layout changes fail closed."""
    pages=[p.translate(str.maketrans({'‐':'-','‑':'-','–':'-','−':'-','ﬁ':'fi','ﬂ':'fl'})) for p in pages]
    head=' '.join(' '.join(pages[:5]).split())
    if 'SAMSUNG ELECTRONICS CO., LTD.' not in head.upper() or 'CONSOLIDATED' not in head.upper():raise TtmError('삼성전자 연결 보고서 식별 실패')
    end=date(year,quarter*3,calendar.monthrange(year,quarter*3)[1])
    months={3:'March',6:'June',9:'September',12:'December'}
    if not re.search(rf'{months[end.month]}\s+{end.day},?\s+{year}\b',head,re.I):raise TtmError('보고서 대상 연도·기간 불일치')
    # Use the independent review/audit date, not a guessed release schedule.
    dates=re.findall(r'Seoul,?\s+Korea\s+([A-Za-z]+\s+\d{1,2},?\s+20\d{2})',head,re.I)
    if len(set(dates))!=1:raise TtmError('감사·검토 보고서 확인 가능일 미확인')
    try:available=datetime.strptime(dates[0].replace(',',''),'%B %d %Y').date()
    except ValueError:raise TtmError('보고서 일자 형식 미확인') from None
    if available<=end or available>today:raise TtmError('보고서 확인 가능일·대상 기간 불일치')
    sections=[]
    for i,page in enumerate(pages):
        compact=' '.join(page.split())
        m=re.search(r'Earnings per Share\s+(?:Earnings per share for the|\(A\)\s*Basic earnings per share)',compact,re.I)
        if not m:continue
        block=' '.join((' '.join(pages[i:i+2])).split())[m.start():]
        eps_context=block
        basic=re.search(r'\(A\)\s*Ordinary shares\s*\(1\)\s*Basic earnings per share(.*?)(?:\(2\)\s*Diluted|\(B\)\s*Preference)',block,re.I)
        if basic:sections.append((i+1,basic.group(1),eps_context))
        elif quarter==4:
            legacy=re.search(r'\(A\)\s*Basic earnings per share.*?\(1\)\s*Ordinary shares(.*?)\(2\)\s*Preference shares',block,re.I)
            if legacy:sections.append((i+1,legacy.group(1),eps_context))
    if len(sections)!=1:raise TtmError('보통주 기본 EPS 주석 위치·중복 확인 필요')
    page,block,eps_context=sections[0]
    if not re.search(r'millions of Korean won(?: and|,) thousands of (?:number of )?shares',block,re.I):raise TtmError('EPS 주석 금액·주식수 단위 미확인')
    if not re.search(rf'\b{year}\s+{year-1}\b',block):raise TtmError('EPS 주석 비교연도 불일치')
    flags=bool(re.search(r'(share split|stock split|bonus issue|retrospectively adjust)',eps_context,re.I))
    def values(label):
        match=re.search(label+r'\s+((?:\(?-?\d[\d,]*(?:\.\d+)?\)?\s*)+)',block,re.I)
        if not match:raise TtmError('EPS 주석 필수 계정 미확인')
        nums=[numeric(v) for v in re.findall(r'\(?-?\d[\d,]*(?:\.\d+)?\)?',match.group(1))]
        expected=2 if quarter in (1,4) else 4
        if len(nums)!=expected or any(v is None for v in nums):raise TtmError('EPS 주석 숫자 열 개수 불일치')
        return nums
    profits=values(r'Profit for the (?:year|period) (?:attributable to|available for) ordinary shares')
    shares=values(r'Weighted-average number of ordinary shares outstanding')
    eps=values(r'Basic earnings per ordinary share \(in Korean won\)')
    # Interim report headers must explicitly identify current/prior cumulative columns.
    if quarter in (2,3) and not re.search(rf'3 Months\s+{quarter*3} Months\s+3 Months\s+{quarter*3} Months',block,re.I):raise TtmError('분기·누적 열 순서 미확인')
    indices=(0,1) if quarter in (1,4) else (1,3)
    output=[]
    for idx,y in zip(indices,(year,year-1)):
        output.append({'period_start':f'{y}-01-01','period_end':date(y,end.month,end.day).isoformat(),
            'profit':profits[idx]*1e6,'weighted_shares':shares[idx]*1e3,'reported_eps':eps[idx],
            'basis':'CFS','currency':'KRW','definition':'ordinary_basic','share_adjustment_flag':flags,
            'source':url,'source_location':f'PDF {page}쪽 EPS 주석 (A)(1)','document_sha256':digest,'available_on':available.isoformat(),'available_on_type':'audit_review_report_date'})
    return output


def listed_samsung_reports():
    import requests
    try:
        with requests.get(INDEX,timeout=(4,12),allow_redirects=False,stream=True) as r:
            if r.status_code!=200:raise TtmError('공식 IR 보고서 목록 응답 실패 · HTTP '+str(r.status_code))
            chunks=[];size=0
            for part in r.iter_content(65536):
                size+=len(part)
                if size>2000000:raise TtmError('공식 IR 목록 크기 한도 초과')
                chunks.append(part)
            html=b''.join(chunks).decode('utf-8')
    except requests.RequestException:raise TtmError('공식 IR 보고서 목록 연결 실패') from None
    return parse_listing(html)


def parse_listing(html):
    class Links(HTMLParser):
        def __init__(self):super().__init__();self.found=set()
        def handle_starttag(self,tag,attrs):
            if tag!='a':return
            href=dict(attrs).get('href','')
            match=re.fullmatch(re.escape(ROOT)+r'(20\d{2})_con_quarter0([1-4])_all\.pdf',urljoin(INDEX,href))
            if match:self.found.add((int(match[1]),int(match[2])))
    parser=Links();parser.feed(html)
    if not parser.found:raise TtmError('공식 IR 보고서 링크 미확인 · 페이지 형식 변경 가능')
    return parser.found


def collect_samsung(today,download=download_pdf,extract=pdf_text,listed=None):
    cache={}
    def report(y,q):
        if (y,q) not in cache:
            url=ROOT+f'{y}_con_quarter0{q}_all.pdf'
            body=download(url)
            cache[y,q]=parse_samsung(extract(body),y,q,url,hashlib.sha256(body).hexdigest(),today)
            for row in cache[y,q]:row['fetched_at']=now()
        return cache[y,q]
    listed=listed_samsung_reports() if listed is None else listed
    for y,q in sorted(listed,reverse=True):
        if y not in (today.year,today.year-1) or date(y,q*3,calendar.monthrange(y,q*3)[1])>=today:continue
        current,prior=report(y,q)
        if q!=4 and (y-1,4) not in listed:raise TtmError('공식 IR 목록의 전년도 연간 보고서 미확인')
        inputs=[current] if q==4 else [report(y-1,4)[0],current,prior]
        annual_eps=[];annual_errors=[]
        end_year=date.fromisoformat(inputs[0]['period_end']).year
        for target in range(end_year,end_year-4,-1):
            try:
                if (target,4) not in listed:raise TtmError('공식 IR 목록에 연간 보고서 없음')
                annual_eps.extend(report(target,4))
            except TtmError as exc:annual_errors.append(f'{target}년: {exc}')
        conflicts=[]
        for target in range(end_year-4,end_year):
            duplicates=[r for r in annual_eps if r['period_end']==f'{target}-12-31']
            if len({r['reported_eps'] for r in duplicates})>1:conflicts.append(f'{target}년 인접 공시 EPS 비교값 불일치 · 재작성 확인 필요')
        return {'version':VERSION,'status':'success','code':'005930','inputs':inputs,
            'annual_comparability_gaps':conflicts,
            'annual_eps':[r for r in annual_eps if end_year-4<=date.fromisoformat(r['period_end']).year<=end_year],
            'annual_eps_errors':annual_errors,'source_route':'Samsung official IR PDF',
            'fetched_at':now(),'last_attempt_at':now(),'listing_source':INDEX,
            'latest_scope':'공식 IR 목록에 실제 연결된 완료 기간 보고서 중 최신 자료 · 접근 실패 시 과거 보고서로 자동 하향하지 않음'}
    raise TtmError('최근 2개 사업연도 공식 EPS 주석 미확인')


def collect_dart(provider,code,today):
    """Generic strict path when ordinary-profit and weighted-share concepts are present."""
    corp=provider.corp(code)
    company=provider.dart('company.json',corp_code=corp) or {}
    if str(company.get('acc_mt','')).zfill(2)!='12':raise TtmError('TTM 현재 경로는 확인된 12월 결산 연결 자료만 지원')
    def fetch(y,q):
        report={1:'11013',2:'11012',3:'11014',4:'11011'}[q]
        raw=(provider.dart('fnlttSinglAcntAll.json',corp_code=corp,bsns_year=str(y),reprt_code=report,fs_div='CFS') or {}).get('list',[])
        return raw,report
    def parse(raw,y,q,report,prior=False):
        receipt={r.get('rcept_no') for r in raw}
        if len(receipt)!=1 or not re.fullmatch(r'\d{14}',str(next(iter(receipt)))):raise TtmError('DART TTM 공시번호 누락·혼재')
        receipt=next(iter(receipt));available=date.fromisoformat(f'{receipt[:4]}-{receipt[4:6]}-{receipt[6:8]}')
        if available>today:raise TtmError('기준일 이후 DART 공시')
        if any(str(r.get('bsns_year'))!=str(y) or r.get('reprt_code')!=report or r.get('corp_code',corp)!=corp for r in raw):raise TtmError('DART TTM 기업·보고기간 불일치')
        field=('frmtrm_add_amount' if q in (2,3) else 'frmtrm_q_amount') if prior else ('thstrm_add_amount' if q in (2,3) else 'thstrm_amount')
        def get(names):
            rows=[r for r in raw if r.get('sj_div') in ('IS','CIS') and r.get('account_nm') in names]
            vals=[numeric(r.get(field)) for r in rows]
            if not rows or any(v is None for v in vals) or len(set(vals))!=1:raise TtmError('DART TTM 보통주 순이익·가중평균 주식수·기본 EPS 누락 또는 불일치')
            if any(r.get('currency')!='KRW' for r in rows):raise TtmError('DART TTM 통화 미확인')
            return vals[0]
        target=y-1 if prior else y
        return {'period_start':f'{target}-01-01','period_end':date(target,q*3,calendar.monthrange(target,q*3)[1]).isoformat(),
            'profit':get(('보통주에 귀속되는 당기순이익','보통주에 귀속되는 당기순이익(손실)')),
            'weighted_shares':get(('가중평균유통보통주식수','가중평균 유통보통주식수')),
            'reported_eps':get(('기본주당이익','기본주당이익(손실)','기본주당순이익')),
            'basis':'CFS','currency':'KRW','definition':'ordinary_basic','source':'https://dart.fss.or.kr/dsaf001/main.do?rcpNo='+receipt,
            'document_sha256':None,'available_on':available.isoformat(),'source_location':'DART 전체 재무제표의 보통주 EPS 세부 계정'}
    for y in (today.year,today.year-1):
        for q in (4,3,2,1):
            if date(y,q*3,calendar.monthrange(y,q*3)[1])>=today:continue
            raw,report=fetch(y,q)
            if not raw:continue
            current=parse(raw,y,q,report)
            if q==4:inputs=[current]
            else:
                annual,ar=fetch(y-1,4)
                inputs=[parse(annual,y-1,4,ar),current,parse(raw,y,q,report,prior=True)]
            return {'version':VERSION,'status':'success','code':code,'inputs':inputs,'source_route':'DART CFS ordinary EPS details','fetched_at':now(),'last_attempt_at':now()}
    raise TtmError('TTM용 DART 공시 미확인')


def collect(provider,code,today):
    if code=='005930':
        block=collect_samsung(today)
    else:
        from predash.official import DataError
        try:block=collect_dart(provider,code,today)
        except (TtmError,DataError) as exc:
            if code!='214450':raise
            from predash.pharma_ir import collect as collect_ir
            try:block=collect_ir(today)
            except TtmError as ir_error:raise TtmError(str(exc)+' · 공식 IR: '+str(ir_error)) from None
            block['dart_error']=str(exc)
            from predash.dart_xbrl import collect as collect_xbrl
            try:block=collect_xbrl(provider,today,block)
            except (TtmError,DataError) as xbrl_error:block['xbrl_error']=str(xbrl_error)
            except (ValueError,TypeError,KeyError):block['xbrl_error']='DART XBRL 목록·원문 형식 확인 필요'
            # This independently verified annual result is useful even without an interim TTM.
            return block
    # Validate financial identities independent of the user's displayed quote.
    check=calculate(block,{'close':1,'date':today.isoformat(),'source':'validation'},today)
    hard=[r for r in check['data_gaps'] if not r.startswith(('공시의 반올림','IR 보고서 작성일')) and '0·적자' not in r]
    if hard:raise TtmError(hard[0])
    return block
