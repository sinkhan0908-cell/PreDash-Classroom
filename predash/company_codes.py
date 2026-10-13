"""Public lookup hints. Each hint must pass live DART company.json validation."""
DIRECTORY_BOOTSTRAP_VERSION = 1

KNOWN_COMPANIES = {
    '005930': {
        'corp_code': '00126380', 'names': ('삼성전자',),
        'source': 'https://englishdart.fss.or.kr/dsbc001/selectPopup.ax?selectKey=00126380',
    },
    '000660': {
        'corp_code': '00164779', 'names': ('SK하이닉스', '에스케이하이닉스'),
        'source': 'https://englishdart.fss.or.kr/dsbc001/selectPopup.ax?selectKey=00164779',
    },
    '214450': {
        'corp_code': '00970453', 'names': ('파마리서치',),
        'source': 'https://dart.fss.or.kr/navi/searchNavi.do?naviCode=A002&naviCrpCik=00970453&naviCrpNm=파마리서치',
    },
}


def company_name_key(name):
    # Only normalize whitespace/case and explicit corporate suffixes, not fuzzy names.
    text = str(name or '').replace('주식회사', '').replace('(주)', '').replace('㈜', '')
    return ''.join(text.split()).casefold()
