import io,unittest
from datetime import date
from unittest.mock import Mock,MagicMock,patch
from predash.pharma_ir import parse_annual,attachment,extract,TtmError,ROOT
from tests_pharma_ir import URL,annual_pages
import predash.dart_network as network

TODAY=date(2026,10,20)


def legacy(year):
    profits,shares,eps=((76551213753,40576699245),(10110790,9975913),(7571,4067)) if year==2023 else ((40576699245,46688655710),(9975913,9898746),(4067,4717))
    table=f'''3. 연결재무제표 주석
38. 주당이익
(1) 기본주당이익
당기 및 전기 중 기본주당이익 계산내역은 다음과 같습니다.
1) 기본주당이익
(단위: 주,원)
구분 당기 전기
지배기업보통주순이익 {profits[0]:,} {profits[1]:,}
가중평균유통보통주식수 {shares[0]:,} {shares[1]:,}
기본주당이익 {eps[0]:,} {eps[1]:,}
2) 보통주에 귀속되는 당기순손익
(2) 희석주당이익
지배기업보통주순이익 999 999
기본주당이익 999 999
39. 현금흐름표
4. 재무제표
38. 주당이익
1) 기본주당이익
(단위: 주,원)
구분 당기 전기
보통주순이익 1 2
가중평균유통보통주식수 1 1
기본주당이익 1 2
2) 보통주에 귀속되는 당기순손익'''
    head=f'사업보고서 사업연도 {year}.01.01 부터 {year}.12.31 까지 한국거래소 귀중 {year+1}년 03월 22일 회사명 : 주식회사 파마리서치 대표이사 : 예시'
    return [head,'','','','','',table]


class LegacyReportTests(unittest.TestCase):
    def test_legacy_consolidated_table_and_prior_years(self):
        for year,receipt,expected in [(2023,'20240315000795',[7571,4067]),(2022,None,[4067,4717])]:
            rows=parse_annual(legacy(year),year,URL,'hash',receipt,TODAY)
            self.assertEqual([r['reported_eps'] for r in rows],expected)
            self.assertEqual(rows[0]['receipt'],receipt)
            if receipt is None:
                self.assertEqual(rows[0]['available_on'],'2023-03-22')
                self.assertEqual(rows[0]['available_on_type'],'report_submission_date')
    def test_no_consolidated_scope_or_unit_mismatch_cannot_validate(self):
        for old,new in [('3. 연결재무제표 주석','5. 재무제표 주석'),('단위: 주,원','단위: 주,천원'),('지배기업보통주순이익','보통주순이익'),('구분 당기 전기','구분 전기 당기')]:
            with self.assertRaises(TtmError):parse_annual([p.replace(old,new) for p in legacy(2022)],2022,URL,'hash',None,TODAY)
    def test_no_receipt_needs_report_submission_date_not_listing_post_date(self):
        detail=f'<a href="{URL}">annual.pdf</a><p>2024.02.07</p>'.encode()
        self.assertEqual(attachment(detail),(URL,None))
        pages=legacy(2022);pages[0]=pages[0].replace('한국거래소 귀중 2023년 03월 22일','')
        with self.assertRaisesRegex(TtmError,'표지 제출일'):parse_annual(pages,2022,URL,'hash',None,TODAY)
    def test_cover_only_and_encrypted_pdf_have_distinct_reasons(self):
        for count,encrypted,reason in [(1,False,'표지'),(280,True,'암호화'),(600,False,'한도')]:
            reader=MagicMock();reader.pages=[Mock()]*count;reader.is_encrypted=encrypted
            with patch('pypdf.PdfReader',return_value=reader):
                with self.assertRaisesRegex(TtmError,reason):extract(b'%PDF-test')
    def test_current_2025_layout_unchanged(self):
        self.assertEqual(parse_annual(annual_pages(),2025,URL,'hash','20260319001417',TODAY)[0]['reported_eps'],15893)


class ConnectionDiagnosticsTests(unittest.TestCase):
    def address(self):return [(network.socket.AF_INET,network.socket.SOCK_STREAM,6,'',('192.0.2.1',443))]
    def test_dns_failure_stops_before_connect_and_does_not_log_exception(self):
        with patch.object(network,'resolve',side_effect=OSError('DO_NOT_LOG_PRIVATE_URL')),patch.object(network.socket,'socket') as socket:
            result=network.diagnose()
        self.assertEqual(result['stages'][0]['stage'],'DNS');self.assertEqual(result['stages'][0]['status'],'failed')
        socket.assert_not_called();self.assertNotIn('DO_NOT_LOG',str(result))
    def test_tcp_timeout_does_not_claim_key_error(self):
        raw=MagicMock();raw.connect.side_effect=TimeoutError('secret')
        with patch.object(network,'resolve',return_value=self.address()),patch.object(network.socket,'socket',return_value=raw):result=network.diagnose()
        self.assertEqual([(r['stage'],r['status']) for r in result['stages']],[('DNS','success'),('TCP','failed')])
        self.assertNotIn('secret',str(result));raw.close.assert_called_once()
    def test_tls_failure_preserves_prior_successes(self):
        raw=MagicMock();tls=MagicMock();tls.wrap_socket.side_effect=network.ssl.SSLError('private')
        with patch.object(network,'resolve',return_value=self.address()),patch.object(network.socket,'socket',return_value=raw),patch.object(network.ssl,'create_default_context',return_value=tls):result=network.diagnose()
        self.assertEqual(result['stages'][-1]['stage'],'TLS');self.assertEqual(result['stages'][-1]['status'],'failed')
        self.assertNotIn('private',str(result))
    def test_public_http_response_is_not_api_authentication_success(self):
        raw=MagicMock();tls=MagicMock();secure=MagicMock();tls.wrap_socket.return_value=secure
        secure.recv.return_value=b'HTTP/1.1 403 Forbidden\r\n'
        with patch.object(network,'resolve',return_value=self.address()),patch.object(network.socket,'socket',return_value=raw),patch.object(network.ssl,'create_default_context',return_value=tls):result=network.diagnose()
        self.assertEqual(result['stages'][-1]['http_status'],403)
        self.assertIn('별도 확인',result['conclusion'])
        sent=secure.sendall.call_args.args[0]
        self.assertNotIn(b'crtfc_key',sent);self.assertNotIn(b'/api/',sent)
        secure.close.assert_called_once()

class FiveYearAndDiagnosticsIntegrationTests(unittest.TestCase):
    def test_five_year_official_eps_survive_cover_only_year_and_missing_receipt(self):
        import predash.pharma_ir as ir
        from predash.valuation_evidence import describe
        from predash.lynch_kis import calculate_reference
        from tests_pharma_ir import annual_block
        listing=''.join(f'<a href="view.html?idx={y}">{y}년 사업보고서</a>' for y in (2025,2024,2023,2022)).encode()
        def download(url):
            if 'list.html' in url:return listing
            if 'view.html' in url:
                year=int(url.split('idx=')[1]);receipt=f'{year+1}0315000001'
                dart=f'<a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}">DART</a>' if year!=2022 else ''
                return (f'<a href="{ROOT}/file_download.php?filename={year}.pdf&filepath=data">report.pdf</a>'+dart).encode()
            return url.split('filename=')[1][:4].encode()
        def read(body):
            year=int(body)
            if year==2024:raise TtmError('공식 IR 첨부가 표지·요약본으로 본문 EPS 없음')
            return annual_pages() if year==2025 else legacy(year)
        b=ir.collect(TODAY,download=download,read=read)
        self.assertEqual({r['period_end'][:4] for r in b['annual_eps']},{'2021','2022','2023','2024','2025'})
        self.assertTrue(any('표지' in e for e in b['annual_eps_errors']))
        self.assertEqual(b['annual_comparability_gaps'],[])
        rows=[{'metric':'KIS EPS','value':v,'year':y,'report_code':'11011','period_type':'연간','period_end':f'{y}-12-31','unit':'원/주'} for y,v in zip(range(2021,2026),(4628,4013,7481,8608,14209))]
        saved={'source':'KIS','data':{'code':'214450','rows':rows,'fetched_at':'2026-10-20T10:00:00+09:00'},'quote':{'close':277500,'date':'2026-10-19','source':'public'},'ttm':b}
        result=describe(saved,calculate_reference(saved,TODAY),TODAY)
        self.assertEqual([r['value'] for r in result['history']],[4717,4067,7571,8941,15893])
        expected=((15893/4717)**.25-1)*100
        self.assertAlmostEqual(result['cagr'],expected)
        self.assertAlmostEqual(result['annual_peg'],(277500/15893)/expected)
        self.assertIsNone(result['per'])
    def test_connect_failure_attaches_safe_server_diagnostics(self):
        from predash.ttm import collect
        from predash.official import DataError
        from tests_pharma_ir import annual_block
        report={'version':1,'host':'opendart.fss.or.kr','conclusion':'TCP 실패','stages':[{'stage':'TCP','status':'failed','elapsed_ms':3000}]}
        with patch('predash.ttm.collect_dart',side_effect=DataError('[CONNECT_TIMEOUT]')),patch('predash.pharma_ir.collect',return_value=annual_block()),patch('predash.dart_xbrl.collect',side_effect=DataError('[CONNECT_TIMEOUT]')),patch('predash.dart_network.diagnose',return_value=report) as probe:
            b=collect(Mock(),'214450',TODAY)
        probe.assert_called_once();self.assertEqual(b['network_diagnostics'],report)
        self.assertEqual(b['annual_eps_status'],'success');self.assertEqual(b['status'],'failed')
