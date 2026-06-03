# -*- coding: utf-8 -*-
import streamlit as st
import requests
import json
import os
import time
from datetime import datetime
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ----------------------------------------------------
# 1. 페이지 초기 설정 및 디자인 테마 정의 (Custom CSS)
# ----------------------------------------------------
st.set_page_config(
    page_title="US Stocks Premium Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# SEC EDGAR 및 Yahoo Finance 관련 헤더 설정
SEC_HEADERS = {
    'User-Agent': 'Gam study-project gam@example.com'
}

# 구글 폰트(Outfit) 로드 및 프리미엄 스타일(그라데이션 타이틀, 글래스모피즘 카드) 적용
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&family=Noto+Sans+KR:wght@300;400;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Outfit', 'Noto Sans KR', sans-serif;
    }
    
    /* 메인 그라데이션 타이틀 */
    .main-title {
        background: linear-gradient(135deg, #1F4E78 0%, #00B0F0 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 800;
        font-size: 2.8rem;
        margin-bottom: 0.2rem;
        text-align: left;
    }
    .sub-title {
        font-size: 1.05rem;
        color: #7F8C8D;
        margin-bottom: 2rem;
        font-weight: 400;
    }
    
    /* 글래스모피즘 메트릭 카드 스타일 */
    .metric-card {
        background: rgba(255, 255, 255, 0.85);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        border: 1px solid rgba(224, 224, 224, 0.6);
        border-radius: 12px;
        padding: 1.2rem;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
        margin-bottom: 1rem;
    }
    .metric-card:hover {
        transform: translateY(-3px);
        box-shadow: 0 8px 20px rgba(0, 0, 0, 0.08);
    }
    .metric-label {
        font-size: 0.85rem;
        color: #7F8C8D;
        font-weight: 600;
        text-transform: uppercase;
        margin-bottom: 0.4rem;
    }
    .metric-value {
        font-size: 1.6rem;
        font-weight: 700;
        color: #1F4E78;
    }
    .metric-delta {
        font-size: 0.9rem;
        font-weight: 600;
        margin-top: 0.2rem;
    }
    .delta-green { color: #2ecc71; }
    .delta-red { color: #e74c3c; }
    .delta-yellow { color: #f1c40f; }
</style>
""", unsafe_allow_html=True)

# ----------------------------------------------------
# 2. API 데이터 로드 및 정제 로직 (캐싱 적용)
# ----------------------------------------------------

@st.cache_data(show_spinner=False)
def get_cik_by_ticker_cached(ticker):
    """최대 3회 재시도 및 지수 백오프를 지원하는 CIK 조회 함수"""
    url = "https://www.sec.gov/files/company_tickers.json"
    ticker_upper = ticker.upper()
    
    for attempt in range(3):
        try:
            r = requests.get(url, headers=SEC_HEADERS, timeout=10)
            if r.status_code == 429:
                time.sleep(2 ** (attempt + 1))
                continue
            r.raise_for_status()
            tickers_data = r.json()
            
            for key, val in tickers_data.items():
                if val['ticker'] == ticker_upper:
                    return val['cik_str'], val['title']
            break
        except Exception:
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))
    return None, None

@st.cache_data(show_spinner="SEC EDGAR에서 재무 정보를 다운로드하는 중...")
def fetch_company_facts_cached(cik):
    """최대 3회 재시도 및 지수 백오프를 지원하는 SEC EDGAR Company Facts 다운로드 함수"""
    cik_padded = f"{cik:010d}"
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json"
    
    for attempt in range(3):
        try:
            r = requests.get(url, headers=SEC_HEADERS, timeout=15)
            if r.status_code == 429:
                time.sleep(2 ** (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))
    return None

def parse_date(date_str):
    if not date_str:
        return None
    return datetime.strptime(date_str, "%Y-%m-%d")

def determine_fye_month(us_gaap):
    fy_months = []
    for concept in ['RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues', 'NetIncomeLoss']:
        if concept in us_gaap:
            units = us_gaap[concept].get('units', {})
            for u in units.values():
                for entry in u:
                    if entry.get('fp') == 'FY' and entry.get('form') == '10-K':
                        end_str = entry.get('end')
                        if end_str:
                            dt = parse_date(end_str)
                            if dt:
                                fy_months.append(dt.month)
            if fy_months:
                break
    if fy_months:
        return max(set(fy_months), key=fy_months.count)
    return 12

def extract_raw_concept_data(us_gaap, tags, fye):
    found_tag = None
    latest_date = ""
    max_entries = -1
    
    for tag in tags:
        if tag not in us_gaap:
            continue
            
        units = us_gaap[tag].get('units', {})
        entries = []
        for u in units.values():
            if isinstance(u, list) and len(u) > 0:
                entries = u
                break
                
        if not entries:
            continue
            
        tag_latest_date = ""
        for entry in entries:
            end_str = entry.get('end')
            if end_str and end_str > tag_latest_date:
                tag_latest_date = end_str
                
        if not found_tag:
            found_tag = tag
            latest_date = tag_latest_date
            max_entries = len(entries)
        else:
            if tag_latest_date > latest_date:
                found_tag = tag
                latest_date = tag_latest_date
                max_entries = len(entries)
            elif tag_latest_date == latest_date:
                if len(entries) > max_entries:
                    found_tag = tag
                    max_entries = len(entries)
                    
    if not found_tag:
        return {}
        
    units = us_gaap[found_tag].get('units', {})
    usd_entries = []
    for u in units.values():
        if isinstance(u, list) and len(u) > 0:
            usd_entries = u
            break
            
    raw_periods = {}
    
    for entry in usd_entries:
        form = entry.get('form')
        if form not in ['10-Q', '10-K']:
            continue
            
        val = entry.get('val')
        start_str = entry.get('start')
        end_str = entry.get('end')
        filed_str = entry.get('filed')
        
        if val is None or not end_str:
            continue
            
        start_date = parse_date(start_str)
        end_date = parse_date(end_str)
        duration_days = (end_date - start_date).days if (start_date and end_date) else 0
        
        end_month = end_date.month
        
        if fye < 12 and end_month > fye:
            fiscal_year = end_date.year + 1
        else:
            fiscal_year = end_date.year
            
        diff = (end_month - fye) % 12
        q_type = None
        
        if duration_days > 0:
            if 80 <= duration_days <= 105:
                if diff == 3: q_type = 'Q1'
                elif diff == 6: q_type = 'Q2'
                elif diff == 9: q_type = 'Q3'
                elif diff == 0: q_type = 'Q4'
            elif 160 <= duration_days <= 200:
                q_type = '6M_YTD'
            elif 240 <= duration_days <= 290:
                q_type = '9M_YTD'
            elif 330 <= duration_days <= 380:
                q_type = 'FY'
        else:
            if diff == 3: q_type = 'Q1'
            elif diff == 6: q_type = 'Q2'
            elif diff == 9: q_type = 'Q3'
            elif diff == 0: q_type = 'Q4'
            
        if not q_type:
            continue
            
        key = (fiscal_year, q_type)
        if key not in raw_periods:
            raw_periods[key] = []
        raw_periods[key].append({
            'val': val,
            'filed': filed_str,
            'end_month': end_month,
            'end_year': end_date.year
        })
        
    cleaned_periods = {}
    for key, entries in raw_periods.items():
        entries.sort(key=lambda x: x['filed'], reverse=True)
        cleaned_periods[key] = {
            'val': entries[0]['val'],
            'end_month': entries[0]['end_month'],
            'end_year': entries[0]['end_year']
        }
        
    return cleaned_periods

@st.cache_data(show_spinner=False)
def process_financial_model_cached(facts_json):
    us_gaap = facts_json['facts'].get('us-gaap', {})
    fye = determine_fye_month(us_gaap)
    
    concept_mappings = {
        'revenue': ['RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues', 'SalesRevenueNet'],
        'cost_of_revenue': ['CostOfRevenue', 'CostOfGoodsAndServicesSold', 'CostOfGoodsSold'],
        'operating_income': ['OperatingIncomeLoss'],
        'rd_expense': ['ResearchAndDevelopmentExpense'],
        'ms_expense': ['SellingAndMarketingExpense', 'MarketingExpense', 'SellingExpense'],
        'ga_expense': ['GeneralAndAdministrativeExpense'],
        'net_income': ['NetIncomeLoss'],
        'ocf': ['NetCashProvidedByUsedInOperatingActivities'],
        'capex': ['PaymentsToAcquirePropertyPlantAndEquipment'],
        'inventory': ['InventoryNet', 'InventoriesNetCurrent', 'Inventories', 'InventoryGross'],
        'receivables': ['AccountsReceivableNetCurrent', 'AccountsReceivableNet', 'AccountsAndNotesReceivableNet'],
        'current_assets': ['AssetsCurrent'],
        'current_liabilities': ['LiabilitiesCurrent'],
        'total_liabilities': ['Liabilities'],
        'long_term_debt': ['LongTermDebt', 'LongTermDebtNoncurrent'],
        'equity': ['StockholdersEquity'],
        'cash': ['CashAndCashEquivalentsAtCarryingValue', 'Cash', 'CashAndCashEquivalentsAtCarryingValueContinuous'],
        
        # 재무상태표 전용 매핑 키 추가
        'bs_assets_current': ['AssetsCurrent'],
        'bs_liabilities_current': ['LiabilitiesCurrent'],
        'bs_long_term_debt': ['LongTermDebt', 'LongTermDebtNoncurrent'],
        'bs_equity': ['StockholdersEquity'],
        'bs_cash': ['CashAndCashEquivalentsAtCarryingValue', 'Cash', 'CashAndCashEquivalentsAtCarryingValueContinuous']
    }
    
    extracted = {}
    for label, tags in concept_mappings.items():
        extracted[label] = extract_raw_concept_data(us_gaap, tags, fye)
        
    all_keys = set()
    for label, periods in extracted.items():
        all_keys.update(periods.keys())
        
    fiscal_years = sorted(list(set([fy for fy, q in all_keys])))
    
    quarter_month_mapping = {1: 'Mar', 2: 'Mar', 3: 'Mar', 4: 'Jun', 5: 'Jun', 6: 'Jun', 
                             7: 'Sep', 8: 'Sep', 9: 'Sep', 10: 'Dec', 11: 'Dec', 12: 'Dec'}
    
    resolved = {label: {} for label in concept_mappings.keys()}
    
    for label in concept_mappings.keys():
        periods = extracted[label]
        for fy in fiscal_years:
            q1_info = periods.get((fy, 'Q1'))
            q1_val = q1_info['val'] if q1_info else None
            if q1_val is not None:
                resolved[label][(fy, 'Q1')] = q1_val
                
            q2_info = periods.get((fy, 'Q2'))
            if q2_info:
                resolved[label][(fy, 'Q2')] = q2_info['val']
            else:
                q2_ytd_info = periods.get((fy, '6M_YTD'))
                if q2_ytd_info and q1_val is not None:
                    resolved[label][(fy, 'Q2')] = q2_ytd_info['val'] - q1_val
                    
            q3_info = periods.get((fy, 'Q3'))
            if q3_info:
                resolved[label][(fy, 'Q3')] = q3_info['val']
            else:
                q3_ytd_info = periods.get((fy, '9M_YTD'))
                q2_ytd_info = periods.get((fy, '6M_YTD'))
                
                if not q2_ytd_info and q1_val is not None:
                    q2_val_calc = resolved[label].get((fy, 'Q2'))
                    if q2_val_calc is not None:
                        q2_ytd_val = q1_val + q2_val_calc
                    else:
                        q2_ytd_val = None
                else:
                    q2_ytd_val = q2_ytd_info['val'] if q2_ytd_info else None
                    
                if q3_ytd_info and q2_ytd_val is not None:
                    resolved[label][(fy, 'Q3')] = q3_ytd_info['val'] - q2_ytd_val
                    
            q4_info = periods.get((fy, 'Q4'))
            if q4_info:
                resolved[label][(fy, 'Q4')] = q4_info['val']
            else:
                fy_info = periods.get((fy, 'FY'))
                if fy_info:
                    q1_c = resolved[label].get((fy, 'Q1'))
                    q2_c = resolved[label].get((fy, 'Q2'))
                    q3_c = resolved[label].get((fy, 'Q3'))
                    if q1_c is not None and q2_c is not None and q3_c is not None:
                        resolved[label][(fy, 'Q4')] = fy_info['val'] - (q1_c + q2_c + q3_c)

    valid_quarters = []
    for fy in fiscal_years:
        if fy < 2021:
            continue
        for q in ['Q1', 'Q2', 'Q3', 'Q4']:
            has_revenue = resolved['revenue'].get((fy, q)) is not None
            has_ocf = resolved['ocf'].get((fy, q)) is not None
            if has_revenue or has_ocf:
                valid_quarters.append((fy, q))
                
    quarter_labels = {}
    for fy, q in valid_quarters:
        diff = {'Q1': 3, 'Q2': 6, 'Q3': 9, 'Q4': 0}[q]
        m = (fye + diff) % 12
        if m == 0: m = 12
        
        y_cal = fy - 1 if (fye < 12 and m > fye) else fy
        y_short = str(y_cal)[2:]
        month_name = quarter_month_mapping[m]
        
        if q == 'Q4':
            label_name = f"{y_short}.{month_name}(10-K)"
        else:
            label_name = f"{y_short}.{month_name}"
            
        quarter_labels[(fy, q)] = label_name
                
    return valid_quarters, quarter_labels, resolved

@st.cache_data(ttl=3600, show_spinner="Yahoo Finance에서 주가 정보를 수집하는 중...")
def fetch_yfinance_data_cached(ticker):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    session = requests.Session()
    session.headers.update(headers)
    
    try:
        session.get("https://fc.yahoo.com/", timeout=10)
    except Exception:
        pass
        
    crumb = None
    try:
        crumb_res = session.get("https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=10)
        if crumb_res.status_code == 200:
            crumb = crumb_res.text.strip()
    except Exception:
        pass
        
    quote_data = {}
    if crumb:
        url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"
        params = {
            "modules": "summaryDetail,defaultKeyStatistics,financialData",
            "crumb": crumb
        }
        try:
            res = session.get(url, params=params, timeout=10)
            if res.status_code == 200:
                quote_data = res.json()
        except Exception:
            pass
            
    price_history = []
    chart_url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
    chart_params = {
        "period1": 1609459200,  # 2021-01-01
        "period2": int(time.time()),
        "interval": "1wk"
    }
    if crumb:
        chart_params["crumb"] = crumb
        
    try:
        res = session.get(chart_url, params=chart_params, timeout=10)
        if res.status_code == 200:
            chart_json = res.json()
            result = chart_json.get('chart', {}).get('result', [{}])[0]
            timestamps = result.get('timestamp', [])
            adjclose = result.get('indicators', {}).get('adjclose', [{}])[0].get('adjclose', [])
            
            for ts, price in zip(timestamps, adjclose):
                if ts is not None and price is not None:
                    dt_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
                    price_history.append((dt_str, price))
    except Exception:
        pass
        
    return quote_data, price_history

def extract_yfinance_metrics(quote_data):
    if not quote_data:
        return {}
    try:
        result = quote_data.get('quoteSummary', {}).get('result', [{}])[0]
    except IndexError:
        return {}
        
    detail = result.get('summaryDetail', {})
    stats = result.get('defaultKeyStatistics', {})
    findata = result.get('financialData', {})
    
    def get_raw(d, key):
        if not isinstance(d, dict):
            return None
        val_obj = d.get(key)
        return val_obj.get('raw') if isinstance(val_obj, dict) else val_obj
        
    metrics = {
        'currentPrice': get_raw(findata, 'currentPrice'),
        'targetMeanPrice': get_raw(findata, 'targetMeanPrice'),
        'marketCap': get_raw(detail, 'marketCap'),
        'trailingPE': get_raw(detail, 'trailingPE'),
        'forwardPE': get_raw(detail, 'forwardPE'),
        'pegRatio': get_raw(stats, 'pegRatio'),
        'priceToBook': get_raw(stats, 'priceToBook'),
        'priceToSales': get_raw(detail, 'priceToSalesTrailing12Months'),
        'roe': get_raw(findata, 'returnOnEquity'),
        'divYield': get_raw(detail, 'dividendYield'),
        'recommendation': findata.get('recommendationKey', 'N/A'),
        'fiftyTwoWeekHigh': get_raw(detail, 'fiftyTwoWeekHigh'),
        'fiftyTwoWeekLow': get_raw(detail, 'fiftyTwoWeekLow')
    }
    return metrics

# ----------------------------------------------------
# 3. 사이드바 검색 영역 구성
# ----------------------------------------------------
st.sidebar.markdown("<h2 style='text-align: center; color: #1F4E78;'>🔍 주식 검색</h2>", unsafe_allow_html=True)
ticker_input = st.sidebar.text_input("미국 주식 티커를 입력하세요:", value="META").strip().upper()
search_button = st.sidebar.button("데이터 분석 실행", use_container_width=True)

# ----------------------------------------------------
# 4. 메인 화면 헤더 영역
# ----------------------------------------------------
st.markdown("<div class='main-title'>▣ US STOCKS PREMIUM RADAR</div>", unsafe_allow_html=True)
st.markdown("<div class='sub-title'>SEC EDGAR 정밀 재무 분석 & 실시간 인터랙티브 시각화 대시보드</div>", unsafe_allow_html=True)

if ticker_input:
    # 1. CIK 정보 로드
    cik, company_full_name = get_cik_by_ticker_cached(ticker_input)
    
    if not cik:
        st.error(f"[-] '{ticker_input}' 티커에 해당하는 CIK를 찾을 수 없습니다. 올바른 미국 주식 티커인지 확인해 주세요.")
    else:
        # 2. 데이터 가져오기
        facts = fetch_company_facts_cached(cik)
        quote_raw, price_history = fetch_yfinance_data_cached(ticker_input)
        yf_metrics = extract_yfinance_metrics(quote_raw)
        
        if not facts:
            st.error(f"[-] CIK {cik:010d} ({company_full_name})의 SEC EDGAR 데이터를 조회하는 데 실패했습니다.")
        else:
            # 3. 재무 데이터 처리
            valid_quarters, quarter_labels, resolved = process_financial_model_cached(facts)
            
            # --- 대시보드 메트릭 연동 준비 ---
            price = yf_metrics.get('currentPrice')
            target = yf_metrics.get('targetMeanPrice')
            
            if price and target:
                upside = (target - price) / price
                upside_str = f"{upside * 100:.1f}%"
                if upside >= 0.20:
                    upside_class = "delta-green"
                elif upside >= 0:
                    upside_class = "delta-yellow"
                else:
                    upside_class = "delta-red"
            else:
                upside_str = "N/A"
                upside_class = ""
                
            mcap = yf_metrics.get('marketCap')
            mcap_str = f"${mcap / 1e9:.1f}B" if mcap else "N/A"
            
            fpe = yf_metrics.get('forwardPE')
            fpe_str = f"{fpe:.2f}x" if fpe else "N/A"
            if fpe:
                if fpe <= 25: fpe_class = "delta-green"
                elif fpe <= 50: fpe_class = "delta-yellow"
                else: fpe_class = "delta-red"
            else:
                fpe_class = ""
                
            peg = yf_metrics.get('pegRatio')
            peg_str = f"{peg:.2f}" if peg else "N/A"
            
            pbr = yf_metrics.get('priceToBook')
            pbr_str = f"{pbr:.2f}x" if pbr else "N/A"
            
            roe = yf_metrics.get('roe')
            roe_str = f"{roe * 100:.2f}%" if roe else "N/A"
            
            div = yf_metrics.get('divYield')
            div_str = f"{div * 100:.2f}%" if div else "0.00%"
            
            recommendation = str(yf_metrics.get('recommendation', 'N/A')).replace('_', ' ').title()
            
            high_52w = yf_metrics.get('fiftyTwoWeekHigh')
            low_52w = yf_metrics.get('fiftyTwoWeekLow')
            if price and high_52w and low_52w and (high_52w > low_52w):
                pos_52w = (price - low_52w) / (high_52w - low_52w) * 100
                pos_52w_str = f"{pos_52w:.1f}%"
            else:
                pos_52w_str = "N/A"
            # PEG Ratio 조건부 서식 설정 (1.5 이하 초록, 2.5 이하 노랑, 2.5 초과 빨강)
            if peg and isinstance(peg, (int, float)):
                if peg <= 1.5:
                    peg_class = "delta-green"
                elif peg <= 2.5:
                    peg_class = "delta-yellow"
                else:
                    peg_class = "delta-red"
            else:
                peg_class = ""
                
            tpe = yf_metrics.get('trailingPE')
            tpe_str = f"{tpe:.2f}x" if tpe else "N/A"
            
            # ----------------------------------------------------
            # 5. UI Layout - 글래스모피즘 메트릭 카드 렌더링
            # ----------------------------------------------------
            st.subheader(f"📊 {company_full_name} ({ticker_input}) 실시간 핵심 지표")
            
            col1, col2, col3, col4, col5, col6 = st.columns(6)
            with col1:
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">현재 주가 (Price)</div>
                    <div class="metric-value">${price if price else 'N/A'}</div>
                    <div class="metric-delta">Target: ${target if target else 'N/A'}</div>
                </div>
                """, unsafe_allow_html=True)
            with col2:
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">상승 여력 (Upside)</div>
                    <div class="metric-value {upside_class}">{upside_str}</div>
                    <div class="metric-delta">Opinion: {recommendation}</div>
                </div>
                """, unsafe_allow_html=True)
            with col3:
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">시가 총액 (Market Cap)</div>
                    <div class="metric-value">{mcap_str}</div>
                    <div class="metric-delta">Div Yield: {div_str}</div>
                </div>
                """, unsafe_allow_html=True)
            with col4:
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">Forward PE</div>
                    <div class="metric-value {fpe_class}">{fpe_str}</div>
                    <div class="metric-delta">Trailing PE: {tpe_str}</div>
                </div>
                """, unsafe_allow_html=True)
            with col5:
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">PEG Ratio</div>
                    <div class="metric-value {peg_class}">{peg_str}</div>
                    <div class="metric-delta">PE / Growth</div>
                </div>
                """, unsafe_allow_html=True)
            with col6:
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">PBR & ROE</div>
                    <div class="metric-value">PBR {pbr_str}</div>
                    <div class="metric-delta">ROE: {roe_str}</div>
                </div>
                """, unsafe_allow_html=True)
                
            # ----------------------------------------------------
            # 6. 메인 콘텐츠 탭 분할
            # ----------------------------------------------------
            tab_summary, tab_tables, tab_charts = st.tabs(["📌 대시보드 요약", "📋 연결 재무제표", "📈 인터랙티브 차트 분석"])
            
            # --- TAB 1: 대시보드 요약 ---
            with tab_summary:
                st.markdown("### 🔍 주요 분석 요약")
                sum_col1, sum_col2 = st.columns([2, 1])
                
                with sum_col1:
                    if price_history:
                        df_history = pd.DataFrame(price_history, columns=["Date", "Close"])
                        fig_hist = go.Figure()
                        fig_hist.add_trace(go.Scatter(x=df_history["Date"], y=df_history["Close"], mode='lines', 
                                                     line=dict(color='#1F4E78', width=2.5), name='주가 (Close)'))
                        fig_hist.update_layout(
                            title=f"최근 2개년 주가 추이 (Weekly Close)",
                            xaxis_title="날짜", yaxis_title="주가 (USD)",
                            template="plotly_white", height=380,
                            margin=dict(l=20, r=20, t=40, b=20)
                        )
                        st.plotly_chart(fig_hist, use_container_width=True)
                    else:
                        st.info("주가 히스토리 데이터를 불러올 수 없습니다.")
                        
                with sum_col2:
                    st.markdown("#### 💡 Valuation & 52주 범위 정보")
                    st.markdown(f"""
                    - **52주 최고가**: `${high_52w if high_52w else 'N/A'}`
                    - **52주 최저가**: `${low_52w if low_52w else 'N/A'}`
                    - **현재가 위치 (%)**: `{pos_52w_str}` *(최저가 0% ~ 최고가 100% 기준)*
                    - **Trailing PE**: `{yf_metrics.get('trailingPE', 'N/A'):.2f}x`
                    - **Price to Sales (PSR)**: `{yf_metrics.get('priceToSales', 'N/A'):.2f}x`
                    """)
                    
                    st.markdown("#### 📋 밸류에이션 리스크 체크")
                    if fpe and fpe > 50:
                        st.warning("⚠️ **FWD PE가 50 초과**로, 밸류에이션 부담이 높은 고PER 상태입니다.")
                    elif fpe and fpe <= 25:
                        st.success("✅ **FWD PE가 25 이하**로, 매력적인 밸류에이션 구간에 진입해 있습니다.")
                    else:
                        st.info("ℹ️ **FWD PE가 25~50 사이**로, 적정 성장주의 밸류에이션 범위 내에 위치합니다.")
                        
                    if upside and upside >= 0.20:
                        st.success(f"🚀 목표주가 대비 **상승여력({upside_str})이 20% 이상**으로 투자의견이 긍정적입니다.")
                    elif upside and upside < 0:
                        st.error(f"📉 현재 주가가 애널리스트 목표가보다 높아 **상승여력이 음수({upside_str})**입니다. 단기 고점 리스크를 주의하세요.")
            
            # --- 데이터 정제 및 테이블 렌더링 준비 ---
            # 각 분기별 데이터 매핑 데이터 프레임 구축
            cols = [quarter_labels[key] for key in valid_quarters]
            
            def get_df_row(label_key, division=1000000.0):
                row_vals = []
                for fy, q in valid_quarters:
                    val = resolved[label_key].get((fy, q))
                    row_vals.append(val / division if val is not None else 0.0)
                return row_vals
                
            # --- TAB 2: 연결 재무제표 ---
            with tab_tables:
                st.markdown("### 📋 연결 재무제표 (in Millions USD)")
                
                sheet_tabs = st.tabs(["손익계산서 (Income)", "손익 성장률 (Growth)", "현금흐름표 (Cash Flow)", "재무상태표 (Balance Sheet)"])
                
                # 1. 손익계산서
                with sheet_tabs[0]:
                    df_income = pd.DataFrame(index=[
                        "매출액 (Revenue)", "매출원가 (Cost of Revenue)", "매출원가율 (%)",
                        "매출총이익 (Gross Profit)", "GPM (%)", "판관비 (SG&A)", "판관비율 (%)",
                        "영업이익 (Operating Income)", "OPM (%)", "당기순이익 (Net Income)", "NPM (%)"
                    ])
                    
                    rev = get_df_row('revenue')
                    cor = get_df_row('cost_of_revenue')
                    cor_rate = [c/r if r > 0 else 0 for r, c in zip(rev, cor)]
                    gp = [r - c for r, c in zip(rev, cor)]
                    gpm = [g/r if r > 0 else 0 for r, g in zip(rev, gp)]
                    
                    op_inc = get_df_row('operating_income')
                    opm = [o/r if r > 0 else 0 for r, o in zip(rev, op_inc)]
                    sgna = [g - o for g, o in zip(gp, op_inc)]
                    sgna_rate = [s/r if r > 0 else 0 for r, s in zip(rev, sgna)]
                    
                    net_inc = get_df_row('net_income')
                    npm = [n/r if r > 0 else 0 for r, n in zip(rev, net_inc)]
                    
                    df_income[cols] = [
                        rev, cor, [x*100 for x in cor_rate],
                        gp, [x*100 for x in gpm], sgna, [x*100 for x in sgna_rate],
                        op_inc, [x*100 for x in opm], net_inc, [x*100 for x in npm]
                    ]
                    
                    # 소수점 반올림 및 Styler 의존성 제거 (Jinja2 충돌 방지)
                    st.dataframe(df_income.round(2), use_container_width=True)
                    
                # 2. 손익 성장률
                with sheet_tabs[1]:
                    df_growth = pd.DataFrame(index=[
                        "매출액 YoY 성장률 (%)", "매출액 QoQ 성장률 (%)",
                        "영업이익 YoY 성장률 (%)", "영업이익 QoQ 성장률 (%)",
                        "당기순이익 YoY 성장률 (%)", "당기순이익 QoQ 성장률 (%)"
                    ])
                    
                    # YoY / QoQ 직접 계산
                    def calc_growth(data_list, mode='YoY'):
                        g_list = []
                        for idx in range(len(data_list)):
                            if mode == 'YoY':
                                if idx >= 4:
                                    prev = data_list[idx - 4]
                                    g_list.append(((data_list[idx] - prev) / prev * 100) if prev != 0 else 0.0)
                                else:
                                    g_list.append(None)
                            else:  # QoQ
                                if idx >= 1:
                                    prev = data_list[idx - 1]
                                    g_list.append(((data_list[idx] - prev) / prev * 100) if prev != 0 else 0.0)
                                else:
                                    g_list.append(None)
                        return g_list
                        
                    df_growth[cols] = [
                        calc_growth(rev, 'YoY'), calc_growth(rev, 'QoQ'),
                        calc_growth(op_inc, 'YoY'), calc_growth(op_inc, 'QoQ'),
                        calc_growth(net_inc, 'YoY'), calc_growth(net_inc, 'QoQ')
                    ]
                    # 소수점 반올림 및 결측치 문자열 대체 (Styler 의존성 제거)
                    st.dataframe(df_growth.round(2).fillna("-"), use_container_width=True)
                    
                # 3. 현금흐름표
                with sheet_tabs[2]:
                    df_cf = pd.DataFrame(index=[
                        "영업현금흐름 (OCF)", "자본지출 (CAPEX)", "잉여현금흐름 (FCF)"
                    ])
                    ocf = get_df_row('ocf')
                    capex = get_df_row('capex')
                    fcf = [o - c for o, c in zip(ocf, capex)]
                    
                    df_cf[cols] = [ocf, capex, fcf]
                    st.dataframe(df_cf.round(2), use_container_width=True)
                    
                # 4. 재무상태표 (Balance Sheet)
                with sheet_tabs[3]:
                    df_bs = pd.DataFrame(index=[
                        "유동자산 (Current Assets)", "유동부채 (Current Liabilities)", "총부채 (Total Liabilities)",
                        "장기부채 (Long Term Debt)", "자기자본 (Equity)", "현금 및 현금성자산 (Cash)",
                        "재고자산 (Inventory)", "매출채권 (Receivables)",
                        "유동비율 (Current Ratio)", "부채비율 (Debt/Equity)", "순부채 (Net Debt)",
                        "재고자산회전율 (Turnover)", "매출채권회전율 (Turnover)"
                    ])
                    
                    cur_ass = get_df_row('bs_assets_current')
                    cur_liab = get_df_row('bs_liabilities_current')
                    tot_liab = get_df_row('total_liabilities')
                    lt_debt = get_df_row('bs_long_term_debt')
                    equity = get_df_row('bs_equity')
                    cash_val = get_df_row('bs_cash')
                    inv = get_df_row('inventory')
                    receiv = get_df_row('receivables')
                    
                    cur_ratio = [a/l if l > 0 else 0 for a, l in zip(cur_ass, cur_liab)]
                    de_ratio = [l/e if e > 0 else 0 for l, e in zip(tot_liab, equity)]
                    net_debt = [d - c for d, c in zip(lt_debt, cash_val)]
                    inv_turn = [c/i if i > 0 else 0 for c, i in zip(cor, inv)]
                    receiv_turn = [r/re if re > 0 else 0 for r, re in zip(rev, receiv)]
                    
                    df_bs[cols] = [
                        cur_ass, cur_liab, tot_liab, lt_debt, equity, cash_val, inv, receiv,
                        cur_ratio, de_ratio, net_debt, inv_turn, receiv_turn
                    ]
                    st.dataframe(df_bs.round(2), use_container_width=True)

            # --- TAB 3: 인터랙티브 차트 분석 ---
            with tab_charts:
                st.markdown("### 📊 인터랙티브 시각화 차트")
                
                # ----------------------------------------------------
                # Chart 1: 매출액, 영업이익, 마진율 및 주가 비교 추이
                # ----------------------------------------------------
                # 각 분기별 종료 월 기준 주가를 price_history에서 탐색하여 매칭
                us_gaap = facts['facts'].get('us-gaap', {})
                fye = determine_fye_month(us_gaap)
                
                q_prices = []
                for fy, q in valid_quarters:
                    diff = {'Q1': 3, 'Q2': 6, 'Q3': 9, 'Q4': 0}[q]
                    m = (fye + diff) % 12
                    if m == 0: m = 12
                    y_cal = fy - 1 if (fye < 12 and m > fye) else fy
                    target_dt_str = f"{y_cal}-{m:02d}-28"
                    
                    best_price = None
                    if price_history:
                        min_diff = float('inf')
                        target_dt = datetime.strptime(target_dt_str, "%Y-%m-%d")
                        for dt_s, pr in price_history:
                            try:
                                dt = datetime.strptime(dt_s, "%Y-%m-%d")
                                diff_days = abs((dt - target_dt).days)
                                if diff_days < min_diff:
                                    min_diff = diff_days
                                    best_price = pr
                            except Exception:
                                pass
                    q_prices.append(best_price if best_price is not None else 0.0)

                fig1 = make_subplots(specs=[[{"secondary_y": True}]])
                fig1.add_trace(go.Bar(x=cols, y=rev, name='매출액 (Revenue)', marker_color='#1F4E78'), secondary_y=False)
                fig1.add_trace(go.Bar(x=cols, y=op_inc, name='영업이익 (Operating Income)', marker_color='#00B0F0'), secondary_y=False)
                
                # 마진율 (우측 Y축 1)
                fig1.add_trace(go.Scatter(x=cols, y=[x*100 for x in opm], name='OPM (%)', 
                                          line=dict(color='#2ecc71', width=3), mode='lines+markers'), secondary_y=True)
                fig1.add_trace(go.Scatter(x=cols, y=[x*100 for x in gpm], name='GPM (%)', 
                                          line=dict(color='#e67e22', width=2.5, dash='dash'), mode='lines+markers'), secondary_y=True)
                
                # 주가 (우측 Y축 2 - 3중 축 시뮬레이션을 위해 yaxis="y3" 사용)
                fig1.add_trace(go.Scatter(x=cols, y=q_prices, name='주가 (Stock Price)', 
                                          line=dict(color='#9b59b6', width=2.5), mode='lines+markers', yaxis="y3"))
                
                fig1.update_layout(
                    title_text="매출액, 영업이익, 마진율(OPM/GPM) 및 주가 비교 추이",
                    xaxis_title="분기",
                    yaxis=dict(
                        title="USD (Millions)",
                        titlefont=dict(color="#1F4E78"),
                        tickfont=dict(color="#1F4E78")
                    ),
                    yaxis2=dict(
                        title="Margin (%)",
                        titlefont=dict(color="#2ecc71"),
                        tickfont=dict(color="#2ecc71"),
                        ticksuffix="%",
                        anchor="x",
                        overlaying="y",
                        side="right"
                    ),
                    yaxis3=dict(
                        title="주가 (USD)",
                        titlefont=dict(color="#9b59b6"),
                        tickfont=dict(color="#9b59b6"),
                        ticksuffix="$",
                        anchor="free",
                        overlaying="y",
                        side="right",
                        position=0.92
                    ),
                    margin=dict(r=80),
                    barmode='group',
                    template="plotly_white",
                    height=500
                )
                st.plotly_chart(fig1, use_container_width=True)
                
                # ----------------------------------------------------
                # Chart 2: 마진율 추이 (GPM, OPM, 판관비율)
                # ----------------------------------------------------
                fig2 = go.Figure()
                fig2.add_trace(go.Scatter(x=cols, y=[x*100 for x in gpm], name='GPM (%)', line=dict(color='#1F4E78', width=2.5), mode='lines+markers'))
                fig2.add_trace(go.Scatter(x=cols, y=[x*100 for x in sgna_rate], name='판관비율 (%)', line=dict(color='#e74c3c', width=2.5), mode='lines+markers'))
                fig2.add_trace(go.Scatter(x=cols, y=[x*100 for x in opm], name='OPM (%)', line=dict(color='#2ecc71', width=3), mode='lines+markers'))
                
                fig2.update_layout(
                    title_text="매출총이익률(GPM) vs 판관비율 vs 영업이익률(OPM)",
                    xaxis_title="분기",
                    yaxis_title="Margin (%)",
                    yaxis_ticksuffix="%",
                    template="plotly_white",
                    height=450
                )
                st.plotly_chart(fig2, use_container_width=True)
                
                # ----------------------------------------------------
                # Chart 3: OCF, CAPEX, FCF 현금흐름 추이
                # ----------------------------------------------------
                fig3 = go.Figure()
                fig3.add_trace(go.Scatter(x=cols, y=ocf, name='영업현금흐름 (OCF)', fill='tozeroy', line=dict(color='rgba(31, 78, 120, 0.7)')))
                fig3.add_trace(go.Scatter(x=cols, y=capex, name='자본지출 (CAPEX)', line=dict(color='#e74c3c', width=2)))
                fig3.add_trace(go.Scatter(x=cols, y=fcf, name='잉여현금흐름 (FCF)', line=dict(color='#2ecc71', width=3)))
                
                fig3.update_layout(
                    title_text="영업현금흐름 (OCF) & CAPEX & FCF 추이",
                    xaxis_title="분기",
                    yaxis_title="USD (Millions)",
                    template="plotly_white",
                    height=450
                )
                st.plotly_chart(fig3, use_container_width=True)
                
                # ----------------------------------------------------
                # Chart 4: 재고자산 및 회전율 추이
                # ----------------------------------------------------
                fig4 = make_subplots(specs=[[{"secondary_y": True}]])
                fig4.add_trace(go.Bar(x=cols, y=inv, name='재고자산 (Inventory)', marker_color='#95a5a6'), secondary_y=False)
                fig4.add_trace(go.Scatter(x=cols, y=inv_turn, name='재고자산회전율 (Turnover)', 
                                          line=dict(color='#d35400', width=2.5), mode='lines+markers'), secondary_y=True)
                
                fig4.update_layout(
                    title_text="재고자산 및 재고자산회전율 추이",
                    xaxis_title="분기",
                    yaxis_title="USD (Millions)",
                    yaxis2_title="Turnover Ratio",
                    template="plotly_white",
                    height=450
                )
                st.plotly_chart(fig4, use_container_width=True)
else:
    st.info("분석할 미국 주식 티커를 사이드바에 입력한 후 '데이터 분석 실행' 버튼을 누르세요.")
