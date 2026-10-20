"""Independent, bounded PharmaResearch official IR annual-EPS route.

Never treat an annual report as the latest interim TTM when interim inputs are absent.
"""
import hashlib
import io
import re
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urljoin,urlsplit,parse_qs
from predash.ttm import TtmError,now,calculate,VERSION

ROOT='https://pharmaresearch.com'
INDEX=ROOT+'/sub/ir/list.html?curpage=1'
CODE='214450'
CORP='00970453'
PARSER_VERSION=2


def compact(text):return re.sub(r'\s+','',text)


def fetch(url):
    import requests
    parts=urlsplit(url)
    if parts.scheme!='https' or parts.netloc!='pharmaresearch.com' or parts.fragment:
        raise TtmError('공식 IR 주소 확인 필요')
    if parts.path in ('/sub/ir/list.html','/sub/ir/view.html'):
        limit=2000000
    elif parts.path=='/file_download.php':
        query=parse_qs(parts.query)
        if query.get('filepath')!=['data'] or not re.fullmatch(r'\d+\.pdf',query.get('filename',[''])[0]):
            raise TtmError('공식 IR 첨부 주소 확인 필요')
        limit=16000000
    else:raise TtmError('공식 IR 경로 확인 필요')
    try:
        with requests.get(url,timeout=(4,12),allow_redirects=False,stream=True) as response:
            if response.status_code!=200:raise TtmError('공식 IR 응답 실패 · HTTP '+str(response.status_code))
            chunks=[];size=0
            for chunk in response.iter_content(65536):
                size+=len(chunk)
                if size>limit:raise TtmError('공식 IR 응답 크기 한도 초과')
                chunks.append(chunk)
            return b''.join(chunks)
    except requests.RequestException:raise TtmError('파마리서치 공식 IR 연결 실패 · 이전 성공 자료 유지') from None


class Links(HTMLParser):
    def __init__(self):super().__init__();self.links=[];self.active=None
    def handle_starttag(self,tag,attrs):
        if tag=='a':self.active=[dict(attrs).get('href',''),'']
    def handle_data(self,data):
        if self.active is not None:self.active[1]+=data
    def handle_endtag(self,tag):
        if tag=='a' and self.active is not None:self.links.append(tuple(self.active));self.active=None


def links(body):
    parser=Links();parser.feed(body.decode('utf-8'));return parser.links


def annual_listing(body):
    found={}
    for href,title in links(body):
        match=re.search(r'(20\d{2})년.*사업보고서',title)
        url=urljoin(INDEX,href);part=urlsplit(url)
        if match and part.netloc=='pharmaresearch.com' and part.path=='/sub/ir/view.html':
            year=int(match[1])
            if year in found and found[year]!=url:raise TtmError('IR 사업보고서 중복 · 정정 여부 확인 필요')
            found[year]=url
    return found


def attachment(body):
    pdfs=[];receipts=[]
    for href,title in links(body):
        url=urljoin(INDEX,href);part=urlsplit(url);query=parse_qs(part.query)
        if part.netloc=='pharmaresearch.com' and part.path=='/file_download.php' and '.pdf' in title.lower():pdfs.append(url)
        if part.scheme=='https' and part.netloc=='dart.fss.or.kr' and part.path=='/dsaf001/main.do':
            receipt=query.get('rcpNo',[''])[0]
            if re.fullmatch(r'\d{14}',receipt):receipts.append(receipt)
    if len(set(pdfs))!=1 or len(set(receipts))>1:raise TtmError('공식 IR 보고서 첨부·DART 접수번호 확인 필요')
    return pdfs[0],receipts[0] if receipts else None


def extract(body):
    if not body.startswith(b'%PDF-'):raise TtmError('공식 IR 첨부가 PDF가 아닙니다.')
    try:
        from pypdf import PdfReader
        reader=PdfReader(io.BytesIO(body))
        if reader.is_encrypted:raise TtmError('IR PDF 암호화로 본문 읽기 불가')
        if len(reader.pages)<10:raise TtmError('공식 IR 첨부가 표지·요약본으로 본문 EPS 없음')
        if len(reader.pages)>500:raise TtmError('IR PDF 페이지 한도 초과')
        return [page.extract_text() or '' for page in reader.pages]
    except TtmError:raise
    except Exception:raise TtmError('공식 IR PDF 읽기 실패 · 이전 성공 자료 유지') from None


def basic_values(text):
    """One ordinary basic block only; diluted and preference values cannot substitute."""
    text=compact(text).split('희석주당')[0]
    def value(pattern):
        matches=re.findall(pattern+r'(\(?-?\d[\d,]*(?:\.\d+)?\)?)',text)
        if len(matches)!=1:raise TtmError('공시 기본 EPS 필수 계정 누락·중복')
        raw=matches[0].replace(',','')
        number=-float(raw[1:-1]) if raw.startswith('(') and raw.endswith(')') else float(raw)
        return number
    return (value(r'지배기업의보통주에귀속되는당기순이익\(손실\)'),
            value(r'가중평균유통보통주식수'),value(r'기본주당이익\(손실\)'))


def parse_annual(pages,year,url,digest,receipt,today):
    head=compact(' '.join(pages[:6]))
    if not re.search(r'회사명[:：]?주식회사파마리서치(?=대표이사)',head):raise TtmError('IR 보고서 회사명 불일치')
    if f'{year}.01.01' not in head or f'{year}.12.31' not in head or '사업보고서' not in head:raise TtmError('IR 보고서 사업연도·기간 확인 필요')
    availability_type='filing_receipt_date'
    if receipt:
        try:available=date.fromisoformat(f'{receipt[:4]}-{receipt[4:6]}-{receipt[6:8]}')
        except ValueError:raise TtmError('IR 접수번호 날짜 확인 필요') from None
    else:
        dates=re.findall(r'한국거래소귀중(20\d{2})년(\d{1,2})월(\d{1,2})일',head)
        if len(set(dates))!=1:raise TtmError('IR 보고서 표지 제출일 확인 필요')
        try:available=date(*map(int,dates[0]))
        except ValueError:raise TtmError('IR 보고서 표지 제출일 오류') from None
        availability_type='report_submission_date'

    if available>today or date(year,12,31)>=available:raise TtmError('IR 보고서 접수일·완료 기간 확인 필요')
    sections=[]
    for i,page in enumerate(pages[6:],6):
        text=compact(' '.join(pages[i:i+2]))
        m=re.search(r'\d+\.주당이익\(연결\)',compact(page))
        if m:
            section=text[m.end():]
            section=re.split(r'\d+\.현금흐름표\(연결\)',section)[0]
            if '당기(단위:원)보통주' in section:sections.append((i+1,section))
    if not sections:
        legacy=legacy_values(pages)
        if legacy:
            page,values=legacy
            return make_rows(values,year,url,digest,receipt,available,availability_type,page,today)
    if len(sections)!=1:raise TtmError('연결 주당이익 주석 위치·형식 확인 필요')
    page,section=sections[0]
    if re.search(r'주식분할|무상증자|소급조정',section):raise TtmError('EPS 주식수 소급조정 대조 필요')
    blocks=re.findall(r'(당기|전기)\(단위:원\)보통주(.*?)(?=(?:당기|전기)\(단위:원\)보통주|$)',section)
    if [name for name,_ in blocks]!=['당기','전기']:raise TtmError('연결 EPS 당기·전기 열 확인 필요')
    return make_rows([basic_values(text) for _,text in blocks],year,url,digest,receipt,available,availability_type,page,today)


def make_rows(values,year,url,digest,receipt,available,availability_type,page,today):
    rows=[]
    for target,(profit,shares,eps) in zip((year,year-1),values):
        row={'period_start':f'{target}-01-01','period_end':f'{target}-12-31','profit':profit,
            'weighted_shares':shares,'reported_eps':eps,'basis':'CFS','currency':'KRW',
            'definition':'ordinary_basic','share_adjustment_flag':False,'source':url,
            'source_location':f'PDF {page}쪽부터 연결 주당이익 주석','document_sha256':digest,
            'available_on':available.isoformat(),'available_on_type':availability_type,'receipt':receipt,
            'fetched_at':now()}
        check=calculate({'version':VERSION,'status':'success','inputs':[row]},
            {'date':today.isoformat(),'close':1,'source':'validation'},today)
        if check['eps'] is None:raise TtmError('공식 IR 순이익·주식수·기본 EPS 대조 실패')
        rows.append(row)
    return rows


def legacy_values(pages):
    # The heading itself has no '(연결)' suffix in older reports. Require the full
    # consolidated-notes scope, then the ordinary-profit label in its basic EPS table.
    text='\n'.join(pages[6:]);starts=list(re.finditer(r'3\.\s*연결재무제표\s*주석',text))
    if len(starts)!=1:return None
    stop=re.search(r'4\.\s*재무제표',text[starts[0].end():])
    if not stop:return None
    begin=starts[0].end();section=text[begin:begin+stop.start()]
    notes=list(re.finditer(r'(?<![\d(])\b\d+\.\s*주당이익\s*(?!\(연결\))',section))
    if len(notes)!=1:return None
    note=section[notes[0].end():]
    basic=re.search(r'1\)\s*기본주당이익(.*?)2\)\s*보통주에',note,re.S)
    if not basic:return None
    table=basic.group(1)
    if not re.search(r'\(단위\s*:\s*주\s*,\s*원\)\s*구분\s*당기\s*전기',table):raise TtmError('과거 EPS 단위·당기/전기 열 확인 필요')
    if re.search(r'주식분할|무상증자|소급조정',table):raise TtmError('EPS 주식수 소급조정 대조 필요')
    def pair(label):
        matches=re.findall(label+r'\s*(\(?-?\d[\d,]*\)?)\s+(\(?-?\d[\d,]*\)?)',table)
        if len(matches)!=1:raise TtmError('과거 연결 기본 EPS 계정 누락·중복')
        def number(v):return -float(v[1:-1].replace(',','')) if v.startswith('(') and v.endswith(')') else float(v.replace(',',''))
        return [number(v) for v in matches[0]]
    profits=pair(r'지배기업\s*보통주\s*순이익')
    shares=pair(r'가중평균유통보통주식수')
    eps=pair(r'기본주당이익')
    # Preserve the actual PDF page containing this note heading.
    prefix=text[:begin+notes[0].start()]
    accumulated=0;page_number=7
    for page_number,page in enumerate(pages[6:],7):
        accumulated+=len(page)+1
        if accumulated>len(prefix):break
    return page_number,list(zip(profits,shares,eps))



def collect(today,download=fetch,read=extract):
    listings=annual_listing(download(INDEX))
    if not listings:raise TtmError('공식 IR 사업보고서 목록 미확인')
    latest=max(y for y in listings if y<today.year) if any(y<today.year for y in listings) else None
    if latest is None or latest<today.year-1:raise TtmError('공식 IR 최근 완료 연간 보고서 미확인')
    selected=dict(listings)
    # Older reports are optional; never guess attachment URLs or use provisional earnings.
    for page in (2,3):
        if all(y in selected for y in range(latest,latest-4,-1)):break
        try:
            for y,url in annual_listing(download(ROOT+f'/sub/ir/list.html?curpage={page}')).items():selected.setdefault(y,url)
        except TtmError:break
    rows=[];errors=[]
    for y in range(latest,latest-4,-1):
        if y not in selected:
            errors.append(f'{y}년 공식 IR 사업보고서 링크 미확인');continue
        try:
            url,receipt=attachment(download(selected[y]));body=download(url)
            rows.extend(parse_annual(read(body),y,url,hashlib.sha256(body).hexdigest(),receipt,today))
        except TtmError as exc:
            if y==latest:raise
            errors.append(f'{y}년: {exc}')
    conflicts=[]
    for y in range(latest-4,latest):
        if len({r['reported_eps'] for r in rows if r['period_end']==f'{y}-12-31'})>1:conflicts.append(f'{y}년 인접 공시 EPS 불일치 · 재작성 확인 필요')
    return {'version':VERSION,'status':'failed','code':CODE,'inputs':[],
        'reason':'공식 IR 연간 EPS 확보 · 최근 누적·전년 동기 EPS 주석 미확보로 TTM 미산출',
        'annual_eps_status':'success','annual_parser_version':PARSER_VERSION,'annual_eps':[r for r in rows if int(r['period_end'][:4])>=latest-4],
        'annual_eps_errors':errors,'annual_comparability_gaps':conflicts,
        'source_route':'PharmaResearch official IR annual reports','listing_source':INDEX,
        'fetched_at':now(),'last_attempt_at':now(),
        'latest_scope':'IR 목록의 최근 완료 연간 자료 · 최신 분기·반기 및 이후 DART 정정 여부는 별도 미확인'}
