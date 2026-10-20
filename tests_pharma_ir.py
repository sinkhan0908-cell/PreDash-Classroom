import io,json,unittest,zipfile,sys,types
try:import requests
except ImportError:sys.modules['requests']=types.SimpleNamespace(RequestException=Exception,request=None)
from copy import deepcopy
from datetime import date,datetime
from zoneinfo import ZoneInfo
from unittest.mock import Mock,MagicMock,patch
import predash.pharma_ir as ir
import predash.official as official
from predash.ttm import TtmError,collect,calculate
from predash.valuation_evidence import describe
from predash.lynch_kis import calculate_reference
from tests_lynch_ui import functions
from predash.dart_xbrl import parse as parse_xbrl,collect as collect_xbrl

TODAY=date(2026,10,19)
URL=ir.ROOT+'/file_download.php?filename=2081071267.pdf&filepath=data&origin_filename=annual.pdf'
RECEIPT='20260319001417'


def annual_pages(year=2025):
    return [f'사업보고서 사업연도 {year}.01.01 부터 {year}.12.31 까지 회사명 : 주식회사 파마리서치 대표이사 : 예시','','','','','',
        '''31. 주당이익 (연결)
주당이익
당기 (단위 : 원) 보통주
지배기업의 보통주에 귀속되는 당기순이익(손실) 165,120,956,459
기본주당이익 가중평균유통보통주식수 10,389,648
기본주당이익(손실) 15,893
희석주당순이익 조정된 가중평균유통보통주식수 11,565,295
희석주당이익(손실) 14,933
전기 (단위 : 원) 보통주
지배기업의 보통주에 귀속되는 당기순이익(손실) 92,043,313,166
기본주당이익 가중평균유통보통주식수 10,294,668
기본주당이익(손실) 8,941
희석주당순이익
32. 현금흐름표 (연결)''']


def annual_block():
    rows=ir.parse_annual(annual_pages(),2025,URL,'hash',RECEIPT,TODAY)
    return {'version':1,'status':'failed','code':'214450','inputs':[],'annual_eps_status':'success',
        'annual_eps':rows,'annual_eps_errors':[],'fetched_at':'2026-10-19T16:00:00+09:00','last_attempt_at':'2026-10-19T16:00:00+09:00','reason':'누적 자료 미확보'}


class PharmaIrTests(unittest.TestCase):
    def test_official_annual_note_selects_ordinary_basic_not_diluted_or_separate(self):
        rows=ir.parse_annual(annual_pages(),2025,URL,'hash',RECEIPT,TODAY)
        self.assertEqual([r['reported_eps'] for r in rows],[15893,8941])
        self.assertEqual(rows[0]['weighted_shares'],10389648)
        self.assertEqual(rows[0]['receipt'],RECEIPT)
    def test_wrong_identity_period_units_section_and_identity_math_fail_closed(self):
        for old,new in [('파마리서치 대표','파마리서치바이오 대표'),('2025.12.31','2026.12.31'),
            ('단위 : 원','단위 : 천원'),('주당이익 (연결)','주당이익 (별도)'),('15,893','142,090')]:
            with self.subTest(old=old):
                with self.assertRaises(TtmError):ir.parse_annual([p.replace(old,new) for p in annual_pages()],2025,URL,'hash',RECEIPT,TODAY)
    def test_future_receipt_split_and_duplicated_note_rejected(self):
        with self.assertRaises(TtmError):ir.parse_annual(annual_pages(),2025,URL,'hash','20270319001417',TODAY)
        with self.assertRaises(TtmError):ir.parse_annual(annual_pages()+annual_pages()[6:],2025,URL,'hash',RECEIPT,TODAY)
        pages=annual_pages();pages[6]+='주식분할'
        # The split appears outside the scoped note, so place it inside the note for this guard.
        pages[6]=pages[6].replace('주당이익\n당기','주당이익 주식분할\n당기')
        with self.assertRaises(TtmError):ir.parse_annual(pages,2025,URL,'hash',RECEIPT,TODAY)
    def test_parenthesized_loss_keeps_negative_sign(self):
        text='지배기업의 보통주에 귀속되는 당기순이익(손실) (100) 가중평균유통보통주식수 10 기본주당이익(손실) (10)'
        self.assertEqual(ir.basic_values(text),(-100,10,-10))
    def test_listing_uses_real_links_not_provisional_earnings(self):
        body=b'<a href="view.html?idx=55">2025\xeb\x85\x84 \xec\x82\xac\xec\x97\x85\xeb\xb3\xb4\xea\xb3\xa0\xec\x84\x9c</a><a href="view.html?idx=58">2026 provisional</a>'
        self.assertEqual(ir.annual_listing(body),{2025:ir.ROOT+'/sub/ir/view.html?idx=55'})
        attachment=(f'<a href="{URL}">annual.pdf</a><a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo={RECEIPT}">DART</a>').encode()
        self.assertEqual(ir.attachment(attachment),(URL,RECEIPT))
        with self.assertRaises(TtmError):ir.attachment(b'<a href="https://example.com/file.pdf">annual.pdf</a>')
    def test_missing_interim_is_not_replaced_by_annual_ttm(self):
        listing='<a href="view.html?idx=55">2025년 사업보고서</a>'.encode()
        detail=(f'<a href="{URL}">annual.pdf</a><a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo={RECEIPT}">DART</a>').encode()
        def download(url):return listing if 'list.html' in url else detail if 'view.html' in url else b'%PDF-source'
        b=ir.collect(TODAY,download=download,read=lambda body:annual_pages())
        self.assertEqual(b['status'],'failed');self.assertEqual(b['annual_eps_status'],'success')
        self.assertEqual(b['inputs'],[]);self.assertEqual(b['annual_eps'][0]['reported_eps'],15893)
        self.assertIsNone(calculate(b,{'close':278000,'date':'2026-10-16','source':'public'},TODAY)['per'])
    def test_annual_only_recalculates_per_without_mixing_unverified_growth(self):
        rows=[{'metric':'KIS EPS','year':y,'report_code':'11011','period_type':'연간','period_end':f'{y}-12-31','unit':'원/주','value':v} for y,v in zip(range(2021,2026),(4628,4013,7481,8608,14209))]
        saved={'source':'KIS','data':{'code':'214450','rows':rows,'fetched_at':'2026-10-19T15:57:32+09:00'},
            'quote':{'date':'2026-10-16','close':278000,'source':'public'},'ttm':annual_block()}
        before=deepcopy(saved);r=describe(saved,calculate_reference(saved,TODAY),TODAY)
        self.assertAlmostEqual(r['annual_per'],278000/15893)
        self.assertEqual(r['valuation_basis']['annual_eps_value'],15893)
        self.assertIsNone(r['cagr']);self.assertIsNone(r['annual_peg']);self.assertIsNone(r['ttm']['per'])
        self.assertEqual(saved,before)
    def test_connect_timeout_does_not_repeat_same_host_as_xml(self):
        with patch.object(official,'get',side_effect=official.DataError('DART 기업개황: 응답 시간이 초과 [CONNECT_TIMEOUT]')) as get:
            with self.assertRaises(official.DataError):official.Official('test','').corp('214450')
            self.assertEqual(get.call_count,1)
    def test_ttm_collector_keeps_independent_annual_when_xbrl_unavailable(self):
        with patch('predash.ttm.collect_dart',side_effect=official.DataError('기업개황 timeout')),patch('predash.pharma_ir.collect',return_value=annual_block()),patch('predash.dart_xbrl.collect',side_effect=official.DataError('공시 목록 timeout')):
            b=collect(Mock(),'214450',TODAY)
        self.assertEqual(b['annual_eps_status'],'success');self.assertEqual(b['status'],'failed')
        self.assertIn('timeout',b['xbrl_error'])
    def test_partial_result_keeps_old_successful_ttm(self):
        old={'version':1,'status':'success','code':'214450','inputs':[{'kept':'original'}],
            'fetched_at':'2026-10-18T00:00:00+09:00','last_attempt_at':'2026-10-18T00:00:00+09:00'}
        st=MagicMock();st.session_state={'lynch_data_214450':{'data':{'code':'214450'},'ttm':old}}
        ns=functions(['lynch_ttm_refresh'],dict(st=st,datetime=datetime,ZoneInfo=ZoneInfo,collect_ttm=Mock(return_value=annual_block()),
            official_client=Mock(),lynch_save_remote=Mock(),TtmError=TtmError,DataError=official.DataError))
        ns['lynch_ttm_refresh']('214450',TODAY,force=True)
        b=st.session_state['lynch_data_214450']['ttm']
        self.assertEqual(b['inputs'],old['inputs']);self.assertEqual(b['fetched_at'],old['fetched_at'])
        self.assertEqual(b['annual_eps'][0]['reported_eps'],15893);self.assertIn('last_error',b)


def xbrl(periods):
    ns='http://xbrl.ifrs.org/taxonomy/2025-03-27/ifrs-full'
    body=f'<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi" xmlns:ifrs-full="{ns}" xmlns:iso4217="http://www.xbrl.org/2003/iso4217">'
    body+='<xbrli:unit id="krw"><xbrli:measure>iso4217:KRW</xbrli:measure></xbrli:unit><xbrli:unit id="shares"><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unit><xbrli:unit id="eps"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:KRW</xbrli:measure></xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>'
    for i,(start,end,eps) in enumerate(periods):
        body+=f'<xbrli:context id="c{i}"><xbrli:entity><xbrli:identifier scheme="company">test-entity</xbrli:identifier><xbrli:segment><xbrldi:explicitMember dimension="ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis">ifrs-full:ConsolidatedMember</xbrldi:explicitMember><xbrldi:explicitMember dimension="ifrs-full:ClassesOfShareCapitalAxis">ifrs-full:OrdinarySharesMember</xbrldi:explicitMember></xbrli:segment></xbrli:entity><xbrli:period><xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context>'
        for name,unit,value in [('ProfitLossAttributableToOrdinaryEquityHoldersOfParentEntity','krw',eps*100),('WeightedAverageNumberOfOrdinarySharesOutstanding','shares',100),('BasicEarningsLossPerShare','eps',eps)]:
            body+=f'<ifrs-full:{name} contextRef="c{i}" unitRef="{unit}" decimals="0">{value}</ifrs-full:{name}>'
    return (body+'</xbrli:xbrl>').encode()


def zipped(body):
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w') as z:z.writestr('instance.xbrl',body)
    return buf.getvalue()


class DartXbrlTests(unittest.TestCase):
    def test_explicit_consolidated_period_and_units_are_required(self):
        period=('2026-01-01','2026-06-30');body=xbrl([(*period,10)])
        rows=parse_xbrl(zipped(body),[period],'20260814002997',TODAY)
        self.assertEqual(rows[0]['reported_eps'],10)
        for old,new in [(b'ConsolidatedMember',b'SeparateMember'),(b'KRW',b'USD'),(b'2026-06-30',b'2026-03-31'),(b'ProfitLossAttributableToOrdinaryEquityHoldersOfParentEntity',b'ProfitLossAttributableToOwnersOfParent')]:
            with self.assertRaises(TtmError):parse_xbrl(zipped(body.replace(old,new)),[period],'20260814002997',TODAY)
    def test_conflicting_facts_external_entities_and_nonzip_rejected(self):
        period=('2026-01-01','2026-06-30');body=xbrl([(*period,10)])
        bad=body.replace(b'</xbrli:xbrl>',b'<ifrs-full:BasicEarningsLossPerShare contextRef="c0" unitRef="eps">999</ifrs-full:BasicEarningsLossPerShare></xbrli:xbrl>')
        for value in (zipped(b'<!DOCTYPE x []>'+body),zipped(bad),b'not zip'):
            with self.assertRaises(TtmError):parse_xbrl(value,[period],'20260814002997',TODAY)
    def test_filing_route_bypasses_company_metadata_but_checks_live_identity(self):
        provider=Mock();provider.dart.return_value={'total_page':1,'list':[
            {'corp_code':'00970453','corp_name':'파마리서치','stock_code':'214450','report_nm':'반기보고서 (2026.06)','rcept_no':'20260814002997'},
            {'corp_code':'00970453','corp_name':'파마리서치','stock_code':'214450','report_nm':'사업보고서 (2025.12)','rcept_no':RECEIPT}]}
        def read(provider,receipt,report):return zipped(xbrl([('2026-01-01','2026-06-30',10),('2025-01-01','2025-06-30',4)] if report=='11012' else [('2025-01-01','2025-12-31',12)]))
        annual=annual_block();annual['annual_eps'][0].update(reported_eps=12,profit=1200,weighted_shares=100)
        b=collect_xbrl(provider,TODAY,annual,read=read)
        self.assertEqual(b['status'],'success');self.assertEqual(len(b['inputs']),3)
        self.assertTrue(all(c.args[0]=='list.json' for c in provider.dart.call_args_list))
        provider.dart.return_value['list'][0]['corp_name']='다른기업'
        with self.assertRaises(TtmError):collect_xbrl(provider,TODAY,annual,read=read)

class PharmaStorageAndTransportTests(unittest.TestCase):
    def test_partial_annual_survives_cloud_roundtrip_without_false_ttm_success(self):
        import tests_financial_store as store_tests
        from predash.financial_store import persist,select_snapshot
        fixture=store_tests.FinancialStoreTests();fixture.setUp()
        saved=deepcopy(fixture.saved);saved['data']['code']='214450';saved['source']='KIS'
        saved['ttm']=annual_block()
        persist(fixture.client,'214450',saved,failed=True,attempt_kind='ttm')
        restored=select_snapshot(fixture.db['payload'],'214450')
        self.assertEqual(restored['ttm']['annual_eps'][0]['reported_eps'],15893)
        self.assertEqual(restored['ttm']['status'],'failed')
        self.assertEqual(restored['ttm']['fetched_at'],saved['ttm']['fetched_at'])
    def test_transport_disallows_unrelated_host_paths_and_unsafe_attachment(self):
        for url in ['http://pharmaresearch.com/sub/ir/list.html','https://example.com/sub/ir/list.html',
            ir.ROOT+'/file_download.php?filename=report.pdf&filepath=../private',ir.ROOT+'/other']:
            with self.assertRaises(TtmError):ir.fetch(url)
    def test_redirect_or_html_disguised_as_pdf_does_not_validate(self):
        response=MagicMock();response.status_code=302
        with patch('requests.get') as request:
            request.return_value.__enter__.return_value=response
            with self.assertRaises(TtmError):ir.fetch(URL)
            self.assertFalse(request.call_args.kwargs['allow_redirects'])
        with self.assertRaises(TtmError):ir.extract(b'<html>not pdf</html>')
    def test_xbrl_restatement_mismatch_does_not_override_verified_ir(self):
        provider=Mock();provider.dart.return_value={'total_page':1,'list':[
            {'corp_code':'00970453','corp_name':'파마리서치','report_nm':'사업보고서 (2025.12)','rcept_no':RECEIPT}]}
        with self.assertRaisesRegex(TtmError,'연간 EPS 불일치'):
            collect_xbrl(provider,TODAY,annual_block(),read=lambda *args:zipped(xbrl([('2025-01-01','2025-12-31',100)])))
    def test_xbrl_multiple_entities_are_not_combined(self):
        body=xbrl([('2026-01-01','2026-06-30',10),('2025-01-01','2025-06-30',5)])
        # Change only the second entity identifier.
        body=body.replace(b'>test-entity</xbrli:identifier>',b'>other-entity</xbrli:identifier>',1)
        with self.assertRaisesRegex(TtmError,'기업 식별자'):
            parse_xbrl(zipped(body),[('2026-01-01','2026-06-30'),('2025-01-01','2025-06-30')],'20260814002997',TODAY)
