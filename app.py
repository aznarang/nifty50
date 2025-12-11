# app.py - Complete Streamlit app (copy-paste into your repo)
import streamlit as st
import pandas as pd
import requests
import time
from io import BytesIO
from pathlib import Path

# Try safe import of yfinance (app will show message if missing)
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except Exception:
    YFINANCE_AVAILABLE = False

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
fmp_key = st.sidebar.text_input("FinancialModelingPrep API key (optional — required for ROCE)", type="password")
st.sidebar.markdown("")  # spacing
fetch_pressed = st.sidebar.button("Fetch Data")   # user must press to start

# Early check: delay crash if yfinance not installed
if not YFINANCE_AVAILABLE:
    st.error(
        "Required package 'yfinance' is not installed in the environment. "
        "Please add 'yfinance' to requirements.txt in the repo and redeploy the app."
    )
    st.stop()

# Helper: HTTP GET with retries
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

# ROCE computation function using FMP annual statements
def compute_roce_for_symbol(fmp_key_local, symbol_no_ns, years=ROCE_YEARS):
    """Return (roce_list_most_recent_first, year_labels)"""
    if not fmp_key_local:
        return [None] * years, [None] * years

    params = {"period":"annual", "limit": years+1, "apikey": fmp_key_local}
    inc_url = f"{FMP_BASE}/income-statement/{symbol_no_ns}"
    bs_url  = f"{FMP_BASE}/balance-sheet-statement/{symbol_no_ns}"
    inc_js = safe_get_json(inc_url, params=params)
    time.sleep(SLEEP_BETWEEN)
    bs_js = safe_get_json(bs_url, params=params)
    time.sleep(SLEEP_BETWEEN)

    if not inc_js or not bs_js:
        return [None]*years, [None]*years

    rows = []
    labels = []
    for i in range(min(years, len(inc_js))):
        inc = inc_js[i] if i < len(inc_js) else {}
        bs = bs_js[i] if i < len(bs_js) else {}
        prev_bs = bs_js[i+1] if (i+1) < len(bs_js) else None
        # label candidate
        label = inc.get('calendarYear') or inc.get('fiscalDate') or inc.get('date')
        labels.append(label)
        # find EBIT-ish
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

# ---------- Nothing happens until user clicks Fetch Data ----------
if not fetch_pressed:
    st.info("Enter an FMP API key in the sidebar (optional) and click **Fetch Data** (sidebar) to begin. Nothing will run until you click.")
    st.stop()

# At this point user clicked Fetch Data -> proceed
# Provide a one-time warning if FMP key missing
if not fmp_key:
    st.warning("No FMP API key provided — ROCE columns will remain empty. Provide an FMP key to compute ROCE.")

# Setup UI slots for progress & status
status_slot = st.empty()
progress_slot = st.progress(0.0)

# STEP 1: fetch market (yfinance) data per stock, show name + ticker progress
status_slot.info("Step 1/2 — fetching market data (price, PE, 52wk) for stocks...")
tickers = FALLBACK_TICKERS.copy()
market_rows = []
total = len(tickers)
for idx, t in enumerate(tickers, start=1):
    name = t
    price = pe = high52 = low52 = None
    try:
        tk = yf.Ticker(t)
        info = tk.info or {}
        name = info.get('shortName') or info.get('longName') or t
        price = info.get('regularMarketPrice') or info.get('previousClose')
        pe = info.get('trailingPE') or info.get('forwardPE')
        high52 = info.get('fiftyTwoWeekHigh') or info.get('52WeekHigh')
        low52 = info.get('fiftyTwoWeekLow') or info.get('52WeekLow')
    except Exception:
        # keep defaults (None) if yfinance read failed for this ticker
        pass

    market_rows.append({"Ticker": t, "Name": name, "Price": price, "PE": pe, "52wkHigh": high52, "52wkLow": low52})
    status_slot.info(f"Step 1/2 — fetching market data for {name} ({t}) — {idx}/{total}")
    # market data phase occupies first 30% of progress
    progress_slot.progress(0.30 * (idx / total))
    time.sleep(SLEEP_BETWEEN)

market_df = pd.DataFrame(market_rows)

# STEP 2: compute ROCE per stock only if key provided
status_slot.info("Step 2/2 — computing ROCE for each stock (if FMP key provided)...")
roce_cols = {f'ROCE_Y{i+1}': [] for i in range(ROCE_YEARS)}
roce_labels = [None]*ROCE_YEARS

for idx, row in enumerate(market_rows, start=1):
    name = row['Name'] or row['Ticker']
    t = row['Ticker']
    status_slot.info(f"Step 2/2 — computing ROCE for {name} ({t}) — {idx}/{total}")
    progress_slot.progress(0.30 + 0.70 * (idx / total))  # remaining 70% for ROCE step
    if fmp_key:
        symbol_no_ns = t.replace(".NS","")
        try:
            vals, yrs = compute_roce_for_symbol(fmp_key, symbol_no_ns, ROCE_YEARS)
        except Exception:
            vals, yrs = [None]*ROCE_YEARS, [None]*ROCE_YEARS
        for i in range(ROCE_YEARS):
            if not roce_labels[i] and yrs and yrs[i]:
                roce_labels[i] = yrs[i]
    else:
        vals = [None]*ROCE_YEARS
    for i, v in enumerate(vals):
        roce_cols[f'ROCE_Y{i+1}'].append(v)
    time.sleep(SLEEP_BETWEEN)

# ---------- Attach ROCE columns safely ----------
num_rows = len(market_df)
for col in list(roce_cols.keys()):
    vals = roce_cols.get(col, [])
    if not isinstance(vals, list):
        vals = [None] * num_rows
    if len(vals) < num_rows:
        vals = vals + [None] * (num_rows - len(vals))
    elif len(vals) > num_rows:
        vals = vals[:num_rows]
    market_df[col] = vals  # safe assignment

# Rename ROCE columns to include year labels if available
rename_map = {}
for i in range(ROCE_YEARS):
    src = f'ROCE_Y{i+1}'
    lab = roce_labels[i] if i < len(roce_labels) else None
    rename_map[src] = f'ROCE_{lab}' if lab else src
market_df = market_df.rename(columns=rename_map)

progress_slot.progress(1.0)
status_slot.success("Fetch + ROCE computation complete.")

# Display the dataframe
st.subheader("Nifty50 data")
st.dataframe(market_df, use_container_width=True)

# ---- Smart filters ----
st.markdown("### Smart filters")
colA, colB, colC, colD = st.columns(4)
with colA:
    top_roce = st.button("Top 5 by latest ROCE")
with colB:
    top_3yr = st.button("Top 5 by 3yr avg ROCE")
with colC:
    low_pe = st.button("Top 5 by lowest PE (positive price)")
with colD:
    momentum = st.button("Top 5 by distance from 52wk low (%)")

def show_top(df_sel, title):
    st.write("**" + title + "**")
    st.table(df_sel.head(5))

if top_roce:
    roce_cols_present = [c for c in market_df.columns if c.startswith("ROCE_")]
    if not roce_cols_present or all(market_df[c].isna().all() for c in roce_cols_present):
        st.warning("ROCE columns not available — provide a valid FMP key in the sidebar and try again.")
    else:
        col = roce_cols_present[0]
        df_valid = market_df[market_df[col].notnull()].sort_values(col, ascending=False)
        show_top(df_valid[['Ticker','Name','Price', col]], "Top 5 by latest ROCE")

if top_3yr:
    roce_cols_present = [c for c in market_df.columns if c.startswith("ROCE_")]
    if len(roce_cols_present) < 3:
        st.warning("Less than 3 ROCE years available.")
    else:
        df_copy = market_df.copy()
        df_copy.loc[:, 'ROCE_3yr_avg'] = df_copy[roce_cols_present[:3]].mean(axis=1, skipna=True)
        df_valid = df_copy[df_copy['ROCE_3yr_avg'].notnull()].sort_values('ROCE_3yr_avg', ascending=False)
        show_top(df_valid[['Ticker','Name','Price','ROCE_3yr_avg']], "Top 5 by 3-year avg ROCE")

if low_pe:
    df_valid = market_df.loc[market_df['Price'].notnull() & market_df['PE'].notnull() & (market_df['Price']>0)]
    df_valid = df_valid.sort_values('PE', ascending=True)
    show_top(df_valid[['Ticker','Name','Price','PE']], "Top 5 by lowest PE")

if momentum:
    df_copy = market_df.copy()
    mask = df_copy['Price'].notnull() & df_copy['52wkLow'].notnull() & (df_copy['52wkLow']>0)
    df_valid = df_copy.loc[mask].copy()
    df_valid.loc[:, 'dist_from_low_pct'] = ((df_valid['Price'] - df_valid['52wkLow']) / df_valid['52wkLow']) * 100
    df_valid = df_valid.sort_values('dist_from_low_pct', ascending=False)
    show_top(df_valid[['Ticker','Name','Price','52wkLow','dist_from_low_pct']], "Top 5 by distance from 52wk low")

# ---- Export to Excel ----
def to_excel_bytes(df_in):
    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as writer:
        df_in.to_excel(writer, index=False, sheet_name='nifty50')
    return out.getvalue()

buf = to_excel_bytes(market_df)
st.download_button("Download Excel", data=buf, file_name=OUT_XLSX, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

st.caption(
    "Notes: ROCE is computed from FMP annual statements (NOPAT / Avg Capital Employed). "
    "Missing values indicate missing financials or API limits. If many None values appear, increase SLEEP_BETWEEN or verify your FMP key/quota."
)
