# app.py (updated per your requests)
import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import time
from io import BytesIO
from pathlib import Path

# ============ CONFIG ============
SLEEP_BETWEEN = 0.6       # increase if you hit API limits
ROCE_YEARS = 5
FMP_BASE = "https://financialmodelingprep.com/api/v3"
OUT_XLSX = "nifty50_data.xlsx"
# embedded fallback ticker list (NSE style) - not shown in UI
FALLBACK_TICKERS = [
    "RELIANCE.NS","TCS.NS","HDFCBANK.NS","INFY.NS","ICICIBANK.NS","HINDUNILVR.NS",
    "ITC.NS","SBIN.NS","BHARTIARTL.NS","KOTAKBANK.NS","LT.NS","AXISBANK.NS","WIPRO.NS",
    "ASIANPAINT.NS","HCLTECH.NS","MARUTI.NS","BAJFINANCE.NS","TITAN.NS","SUNPHARMA.NS",
    "TECHM.NS","NESTLEIND.NS","POWERGRID.NS","ULTRACEMCO.NS","ADANIENT.NS","TATAMOTORS.NS",
    "ONGC.NS","TATASTEEL.NS","JSWSTEEL.NS","NTPC.NS","INDUSINDBK.NS","M&M.NS","COALINDIA.NS",
    "BAJAJFINSV.NS","HINDALCO.NS","DRREDDY.NS","GRASIM.NS","DIVISLAB.NS","BAJAJ-AUTO.NS",
    "BRITANNIA.NS","HEROMOTOCO.NS","ADANIPORTS.NS","CIPLA.NS","UPL.NS","SBILIFE.NS",
    "EICHERMOT.NS","BPCL.NS","TATACONSUM.NS","APOLLOHOSP.NS","SHREECEM.NS","HDFC.NS"
]
# =================================

st.set_page_config(page_title="Nifty50 Explorer", layout="wide")
st.title("Nifty50 Explorer (Satya)")

# ---------------- UI: Auth (simple) ----------------
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.subheader("Login")
    pwd = st.text_input("Enter app password", type="password")
    app_pw = st.secrets.get("APP_PASSWORD") if "APP_PASSWORD" in st.secrets else None
    if st.button("Login"):
        if app_pw and pwd == app_pw:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Invalid password. If running locally, create .streamlit/secrets.toml with APP_PASSWORD.")
    st.stop()

# ---------------- Sidebar: FMP key + Fetch ----------------
st.sidebar.header("Data & Controls")
fmp_key = st.sidebar.text_input("FinancialModelingPrep API key (optional, required for ROCE)", type="password")
st.sidebar.markdown("")  # spacing
fetch_pressed = st.sidebar.button("Fetch Data")   # user must press to start

# Export button on main area (inactive until data ready)
export_main = st.empty()

# helper: safe GET
def safe_get_json(url, params=None, max_retries=3, backoff=1.2):
    headers = {"User-Agent": "Mozilla/5.0"}
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=20)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(backoff * (attempt + 1))
                continue
            return None
        except Exception:
            time.sleep(backoff * (attempt + 1))
    return None

# ROCE computation function
def compute_roce_for_symbol(fmp_key_local, symbol_no_ns, years=ROCE_YEARS):
    """Return (roce_list_most_recent_first, year_labels)"""
    params = {"period":"annual", "limit": years+1, "apikey": fmp_key_local}
    inc_url = f"{FMP_BASE}/income-statement/{symbol_no_ns}"
    bs_url  = f"{FMP_BASE}/balance-sheet-statement/{symbol_no_ns}"
    inc_js = safe_get_json(inc_url, params=params) if fmp_key_local else None
    time.sleep(SLEEP_BETWEEN)
    bs_js = safe_get_json(bs_url, params=params) if fmp_key_local else None
    time.sleep(SLEEP_BETWEEN)

    if not inc_js or not bs_js:
        return [None]*years, [None]*years

    rows = []
    labels = []
    for i in range(min(years, len(inc_js))):
        inc = inc_js[i] if i < len(inc_js) else {}
        bs = bs_js[i] if i < len(bs_js) else {}
        prev_bs = bs_js[i+1] if (i+1) < len(bs_js) else None
        label = inc.get('calendarYear') or inc.get('fiscalDate') or inc.get('date')
        labels.append(label)
        # find EBIT
        ebit = None
        for k in ('ebit','operatingIncome','operatingIncomeLoss'):
            if k in inc and inc.get(k) is not None:
                ebit = inc.get(k); break
        if ebit is None:
            rows.append(None); continue
        # estimate tax rate
        incbt = inc.get('incomeBeforeTax')
        tax = inc.get('incomeTaxExpense')
        if incbt and tax and incbt != 0:
            tax_rate = tax / incbt
            if tax_rate < 0 or tax_rate > 0.6:
                tax_rate = 0.25
        else:
            tax_rate = 0.25
        nopat = ebit * (1 - tax_rate)
        total_assets = bs.get('totalAssets')
        total_current_liab = bs.get('totalCurrentLiabilities') or None
        if total_assets is None or total_current_liab is None:
            rows.append(None); continue
        ce_curr = total_assets - total_current_liab
        if prev_bs:
            prev_assets = prev_bs.get('totalAssets'); prev_curr_liab = prev_bs.get('totalCurrentLiabilities') or None
            if prev_assets is not None and prev_curr_liab is not None:
                ce_prev = prev_assets - prev_curr_liab
                avg_ce = (ce_curr + ce_prev) / 2.0
            else:
                avg_ce = ce_curr
        else:
            avg_ce = ce_curr
        if not avg_ce or avg_ce == 0:
            rows.append(None); continue
        roce_pct = round((nopat / avg_ce) * 100, 2)
        rows.append(roce_pct)
    while len(rows) < years:
        rows.append(None); labels.append(None)
    return rows[:years], labels[:years]

# Nothing should happen until user clicks Fetch Data
if not fetch_pressed:
    st.info("Start by entering an FMP API key (optional) in the sidebar and click **Fetch Data** (sidebar) to begin.")
    st.stop()

# If Fetch pressed: proceed
# Inform about ROCE only once if key missing
if not fmp_key:
    st.warning("No FMP API key provided — ROCE columns will be empty. Provide the key to compute ROCE for each stock.")
time.sleep(0.2)

# Prepare UI slots for progress & status
status_slot = st.empty()
progress_slot = st.progress(0.0)

# STEP 1: fetch market data (yfinance) per stock, show name + ticker progress
status_slot.info("Step 1/2 — fetching market data (price, PE, 52wk) for stocks...")
tickers = FALLBACK_TICKERS.copy()
market_rows = []
total = len(tickers)
for idx, t in enumerate(tickers, start=1):
    try:
        tk = yf.Ticker(t)
        info = tk.info or {}
        name = info.get('shortName') or info.get('longName') or t
        price = info.get('regularMarketPrice') or info.get('previousClose')
        pe = info.get('trailingPE') or info.get('forwardPE')
        high52 = info.get('fiftyTwoWeekHigh') or info.get('52WeekHigh')
        low52 = info.get('fiftyTwoWeekLow') or info.get('52WeekLow')
    except Exception:
        name = t; price = pe = high52 = low52 = None
    market_rows.append({"Ticker": t, "Name": name, "Price": price, "PE": pe, "52wkHigh": high52, "52wkLow": low52})
    # update status showing stock name + ticker
    status_slot.info(f"Step 1/2 — fetching market data for {name} ({t}) — {idx}/{total}")
    progress_slot.progress(0.25 * (idx / total))  # market takes 25% of total progress
    time.sleep(SLEEP_BETWEEN)

market_df = pd.DataFrame(market_rows)

# STEP 2: compute ROCE per stock if key provided (show stock name + ticker)
status_slot.info("Step 2/2 — computing ROCE for each stock (if FMP key provided)...")
roce_cols = {f'ROCE_Y{i+1}': [] for i in range(ROCE_YEARS)}
roce_labels = [None]*ROCE_YEARS

for idx, row in enumerate(market_rows, start=1):
    name = row['Name'] or row['Ticker']
    t = row['Ticker']
    status_slot.info(f"Step 2/2 — computing ROCE for {name} ({t}) — {idx}/{total}")
    progress_slot.progress(0.25 + 0.75 * (idx / total))  # remaining 75% for ROCE step
    if fmp_key:
        symbol_no_ns = t.replace(".NS","")
        vals, yrs = compute_roce_for_symbol(fmp_key, symbol_no_ns, ROCE_YEARS)
        for i in range(ROCE_YEARS):
            if not roce_labels[i] and yrs and yrs[i]:
                roce_labels[i] = yrs[i]
    else:
        vals = [None]*ROCE_YEARS
    for i, v in enumerate(vals):
        roce_cols[f'ROCE_Y{i+1}'].append(v)
    time.sleep(SLEEP_BETWEEN)

# attach ROCE columns safely, no SettingWithCopyWarning
for col, vals in roce_cols.items():
    market_df[col] =_
