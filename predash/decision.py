"""Evidence workspace helpers; coverage is never an investment score."""
import json
from datetime import datetime
from math import isfinite

EVIDENCE_VERSION=2

class EvidenceError(ValueError):pass

def comparison(stock_rows,index_rows,code,today):
    def series(rows,date_key,value_key,stock=False):
        result={}
        for row in rows:
            if stock and str(row.get('srtnCd','')).removeprefix('A').zfill(6)!=code:continue
            try:
                day=datetime.strptime(str(row[date_key]),'%Y%m%d').date()
                value=float(str(row[value_key]).replace(',',''))
                if day>today or not isfinite(value) or value<=0:raise ValueError
            except (KeyError,ValueError,TypeError):raise EvidenceError('비교 시세의 날짜·가격을 확인하지 못했습니다.') from None
            if day in result and result[day]!=value:raise EvidenceError('같은 날짜의 시세가 서로 다릅니다.')
            result[day]=value
        return result
    stocks=series(stock_rows,'basDt','clpr',True)
    market=series(index_rows,'stck_bsop_date','bstp_nmix_prpr')
    days=sorted(stocks.keys() & market.keys())[-20:]
    if len(days)<10:raise EvidenceError('종목·시장에 공통으로 존재하는 거래일이 10개 미만입니다.')
    if (today-days[-1]).days>5:raise EvidenceError('비교 차트의 기준일이 오래됐습니다.')
    base_stock,base_market=stocks[days[0]],market[days[0]]
    return [{'date':d.isoformat(),'stock':stocks[d]/base_stock*100,'market':market[d]/base_market*100} for d in days]

def brief(item):
    lines=[];lamp=item.get('lamp');m=item.get('metrics');flow=item.get('flow')
    if lamp:lines.append(f"종가 추세는 {lamp['state']}입니다. 기준일 {lamp['date']}, 10·20일선 비교입니다.")
    else:lines.append('종가 추세는 자료 부족으로 보류합니다.')
    if m:
        lines.append(f"{m['year']}년 {m['quarter']}분기 누적 매출 {m['revenue']:,.1f}억, 영업이익 {m['profit']:,.1f}억입니다.")
        if m.get('growth_pct') is not None:lines.append(f"전년 동기 누적 영업이익 증가율은 {m['growth_pct']:+.1f}%입니다.")
        else:lines.append('영업이익 증가율은 전년 동기 비교 조건 미충족으로 보류합니다.')
    else:lines.append('매출·영업이익 비교는 공식 자료 부족으로 보류합니다.')
    if flow:
        labels={'foreign':'외국인','institution':'기관','individual':'개인'}
        text=' · '.join(f"{labels[k]} {v:+,}주" for k,v in flow['daily'].items() if k in labels)
        lines.append(f"일별 순매수 수량({flow['date']}): {text}.")
    else:lines.append('투자자 수급은 자료 연결 후 확인하세요.')
    lines.append('산업 성장·수출 변화가 이 기업의 매출로 연결되는지는 제품·고객·수주 근거를 추가 확인하세요.')
    return lines

def export_review(item,comparison_rows,industry,market_name):
    return json.dumps({'schema':'predash-evidence-v1','code':item['code'],'name':item['name'],
        'fetched':item['fetched'],'official_data':{k:item.get(k) for k in ('lamp','metrics','flow','krx','report','exports','financial_snapshot','pc_ttm')},
        'data_errors':item.get('errors',{}),'comparison':{'market':market_name,'base':100,'rows':comparison_rows},
        'industry_note':{'verification':'사용자 기록 · 자동 검증 아님',**industry},
        'brief':brief(item),'investment_score':None},ensure_ascii=False,indent=2)

