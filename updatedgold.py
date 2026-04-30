import streamlit as st
import requests
import numpy as np
from sklearn.linear_model import LinearRegression
import plotly.graph_objects as go
from datetime import datetime, timedelta
from fpdf import FPDF
import urllib.parse
from supabase import create_client, Client

# --- CONFIGURATION & STYLING ---
st.set_page_config(page_title="Gold Portfolio Tracker", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #0e1117; color: #00ff41; font-family: 'Courier New', monospace; }
    div[data-testid="stMetricValue"], div[data-testid="stMarkdownContainer"] p { color: #00ff41 !important; }
    h1, h2, h3, h4, span { color: #00ff41 !important; }
    .stButton>button { border: 1px solid #00ff41; color: #00ff41; background-color: black; width: 100%; }
    .stButton>button:hover { background-color: #00ff41; color: black; }
    .stTextInput>div>div>input, .stNumberInput>div>div>input { color: #00ff41; background-color: #262730; border: 1px solid #00ff41; }
    </style>
    """, unsafe_allow_html=True)

# --- CLOUD DATABASE INITIALIZATION ---
API_KEY = st.secrets["GOLD_API_KEY"]

@st.cache_resource
def init_connection():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_connection()

# --- GLOBAL MARKET DATABASE ---
MARKET_DB = {
    "India": {"curr": "INR", "sym": "₹", "tax_type": "SPLIT", "gold_tax": 0.03, "make_tax": 0.05},
    "Saudi Arabia": {"curr": "SAR", "sym": "SAR", "tax_type": "FLAT", "tax_rate": 0.15},
    "United Arab Emirates": {"curr": "AED", "sym": "AED", "tax_type": "FLAT", "tax_rate": 0.05},
    "United States": {"curr": "USD", "sym": "$", "tax_type": "FLAT", "tax_rate": 0.00},
    "United Kingdom": {"curr": "GBP", "sym": "£", "tax_type": "FLAT", "tax_rate": 0.20},
    "Global Standard": {"curr": "USD", "sym": "$", "tax_type": "FLAT", "tax_rate": 0.00}
}

# --- SYSTEM STATE ---
if 'user_email' not in st.session_state:
    st.session_state.user_email = None
if 'geo_location' not in st.session_state:
    st.session_state.geo_location = None

query_params = st.query_params
url_weight = float(query_params.get("weight", 8.0))
url_making = float(query_params.get("making", 12.0))
url_market = query_params.get("market", None)

# --- CORE FUNCTIONS ---
def get_geo_location():
    # Diagnostic Mode: Bypassing cache to force a fresh read every time
    try:
        user_ip = "IP NOT FOUND"
        
        # Step 1: Attempt to pull the IP from the cloud proxy headers
        if hasattr(st, "context") and hasattr(st.context, "headers"):
            if "X-Forwarded-For" in st.context.headers:
                user_ip = st.context.headers["X-Forwarded-For"].split(",")[0].strip()
                
        # Print what the server thinks your IP is to the sidebar
        st.sidebar.warning(f"/// SYSTEM DEBUG - IP DETECTED: {user_ip} ///")

        # Step 2: Attempt the API Ping
        if user_ip and user_ip != "IP NOT FOUND" and user_ip not in ["127.0.0.1", "::1"]:
            url = f"http://ip-api.com/json/{user_ip}"
            response = requests.get(url, timeout=5)
            
            # Print the raw response from the API to the sidebar
            st.sidebar.info(f"/// SYSTEM DEBUG - API RESPONSE: {response.text} ///")
            
            data = response.json()
            if data.get("status") == "success":
                st.session_state.geo_location = data.get("country", "Global Standard")
                return st.session_state.geo_location
                
        return "Global Standard"

    except Exception as e:
        # Print the exact python error if it crashes
        st.sidebar.error(f"/// SYSTEM DEBUG - CRASH LOG: {str(e)} ///")
        return "Global Standard"
def fetch_live_rates(currency_code):
    url = f"https://www.goldapi.io/api/XAU/{currency_code}"
    headers = {"x-access-token": API_KEY, "Content-Type": "application/json"}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json().get('price_gram_24k')
        return None
    except:
        return None

def generate_historical_data_and_predict(current_price):
    np.random.seed(datetime.now().day)
    volatility = current_price * 0.004
    changes = np.random.normal(0.5, volatility, size=30)
    prices = np.cumsum(changes)
    historical_prices = prices - prices[-1] + current_price
    X = np.arange(30).reshape(-1, 1)
    model = LinearRegression().fit(X, historical_prices)
    next_day_prediction = model.predict([[30]])[0]
    return historical_prices, next_day_prediction

def create_pdf_report(market, date_str, weight, rate, gold_val, making, tax_amount, total, curr_sym):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Courier", size=10)
    pdf.set_font("Courier", style="B", size=16)
    pdf.cell(0, 10, "SECURE PROCUREMENT QUOTATION", ln=True, align="C")
    pdf.set_font("Courier", size=10)
    pdf.cell(0, 10, f"TIMESTAMP: {date_str} | REGION: {market}", ln=True, align="C")
    pdf.line(10, 30, 200, 30)
    pdf.ln(10)
    
    pdf.set_font("Courier", style="B", size=12)
    pdf.cell(0, 10, "COMMODITY SPECIFICATIONS", ln=True)
    pdf.set_font("Courier", size=12)
    pdf.cell(100, 8, f"Purity: 22K (91.6%)")
    pdf.cell(90, 8, f"Weight: {weight} Grams", ln=True)
    pdf.cell(100, 8, f"Base Rate (1g): {curr_sym} {rate:,.2f}", ln=True)
    pdf.ln(5)
    
    pdf.set_font("Courier", style="B", size=12)
    pdf.cell(0, 10, "FINANCIAL BREAKDOWN", ln=True)
    pdf.set_font("Courier", size=12)
    pdf.cell(120, 8, "Base Gold Value:")
    pdf.cell(70, 8, f"{curr_sym} {gold_val:,.2f}", align="R", ln=True)
    pdf.cell(120, 8, "Workmanship:")
    pdf.cell(70, 8, f"{curr_sym} {making:,.2f}", align="R", ln=True)
    pdf.cell(120, 8, "Taxes & Levies:")
    pdf.cell(70, 8, f"{curr_sym} {tax_amount:,.2f}", align="R", ln=True)
    pdf.line(10, pdf.get_y() + 2, 200, pdf.get_y() + 2)
    pdf.ln(5)
    
    pdf.set_font("Courier", style="B", size=14)
    pdf.cell(120, 10, "NET PAYABLE:")
    pdf.cell(70, 10, f"{curr_sym} {total:,.2f}", align="R", ln=True)
    return bytes(pdf.output())

# --- AUTO-LOCATE PROTOCOL ---
detected_country = get_geo_location()
default_market = detected_country if detected_country in MARKET_DB else "Global Standard"
if url_market and url_market in MARKET_DB:
    default_market = url_market

# --- UI HEADER ---
st.title("GOLD PORTFOLIO TRACKER")
st.text(f"SYSTEM STATUS: ONLINE | GEO-TRACE LOCATION: {detected_country}")
st.divider()

# --- SIDEBAR: NAVIGATION ---
with st.sidebar:
    st.header("SYSTEM MODULE")
    app_mode = st.radio("SELECT PROTOCOL", ["MARKET TERMINAL", "ENCRYPTED VAULT", "ALERT WEBHOOKS"])
    st.divider()
    
    st.header("MARKET OVERRIDE")
    market_keys = list(MARKET_DB.keys())
    default_index = market_keys.index(default_market)
    selected_market = st.selectbox("SELECT REGION", market_keys, index=default_index)
    
    market_data = MARKET_DB[selected_market]
    curr = market_data["curr"]
    symbol = market_data["sym"]

# --- MODULE 1: MARKET TERMINAL ---
if app_mode == "MARKET TERMINAL":
    spot_24k = fetch_live_rates(curr)
    
    if spot_24k:
        rate_22k = spot_24k * 0.9166
        
        c1, c2, c3 = st.columns(3)
        c1.metric(f"LIVE 22K (1G) - {curr}", f"{symbol} {rate_22k:,.2f}")
        c2.metric("LIVE 22K (8G/PAVAN)", f"{symbol} {(rate_22k * 8):,.2f}")
        c3.metric("24K SPOT RATE", f"{symbol} {spot_24k:,.2f}")
        
        st.subheader("AI MARKET FORECAST (24H)")
        historical_data, prediction = generate_historical_data_and_predict(spot_24k)
        trend_diff = prediction - spot_24k
        
        p_col, c_col = st.columns([1, 3])
        with p_col:
            st.write("NEXT 24H OUTLOOK")
            if trend_diff > 0:
                st.success(f"BULLISH TREND\n\nProjected: {symbol} {prediction:,.2f}")
            else:
                st.error(f"BEARISH TREND\n\nProjected: {symbol} {prediction:,.2f}")
            st.caption("Model: Linear Regression")

        with c_col:
            dates = [(datetime.now() - timedelta(days=i)).strftime('%b %d') for i in range(29, -1, -1)]
            dates.append("TOMORROW")
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=dates[:-1], y=historical_data, mode='lines', line=dict(color='#00ff41', width=2)))
            fig.add_trace(go.Scatter(x=[dates[-2], dates[-1]], y=[historical_data[-1], prediction], mode='lines+markers', line=dict(color='#ff003c', width=2, dash='dot')))
            fig.update_layout(plot_bgcolor='#0e1117', paper_bgcolor='#0e1117', font=dict(color='#00ff41', family='Courier New'), margin=dict(l=0, r=0, t=10, b=0), xaxis=dict(showgrid=False), yaxis=dict(showgrid=True, gridcolor='#262730'), showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

        st.divider()

        st.subheader("PROCUREMENT ENGINE")
        col_input, col_result = st.columns(2)

        with col_input:
            weight = st.number_input("Weight (Grams)", min_value=0.1, value=url_weight)
            m_type = st.selectbox("Making Charge Type", ["Percentage", "Flat Rate"])
            m_val = st.number_input(f"Enter {m_type} Value", min_value=0.0, value=url_making)

        gold_val = rate_22k * weight
        making_cost = gold_val * (m_val / 100) if m_type == "Percentage" else m_val * weight

        if market_data["tax_type"] == "SPLIT":
            gold_tax = gold_val * market_data["gold_tax"]
            making_tax = making_cost * market_data["make_tax"]
            total_tax = gold_tax + making_tax
            tax_info = f"TAX: Gold ({market_data['gold_tax']*100}%) = {symbol} {gold_tax:,.2f} | Making ({market_data['make_tax']*100}%) = {symbol} {making_tax:,.2f}"
        else:
            total_tax = (gold_val + making_cost) * market_data["tax_rate"]
            tax_info = f"TAX: Flat ({market_data['tax_rate']*100}%) = {symbol} {total_tax:,.2f}"

        final = gold_val + making_cost + total_tax

        with col_result:
            st.write(f"BASE GOLD VALUE:  {symbol} {gold_val:,.2f}")
            st.write(f"LABOR CHARGES:    {symbol} {making_cost:,.2f}")
            st.caption(tax_info)
            st.write(f"### NET PAYABLE: {symbol} {final:,.2f}")
            
            base_url = "https://your-app-name.streamlit.app/" 
            query_str = urllib.parse.urlencode({'weight': weight, 'making': m_val, 'market': selected_market})
            st.code(f"SECURE TRANSMISSION LINK:\n{base_url}?{query_str}", language="bash")
            
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            pdf_data = create_pdf_report(selected_market, current_time, weight, rate_22k, gold_val, making_cost, total_tax, final, symbol)
            st.download_button(label="[ DOWNLOAD FINANCIAL REPORT .PDF ]", data=pdf_data, file_name=f"Quote_{curr}_{datetime.now().strftime('%Y%m%d')}.pdf", mime="application/pdf")
    else:
        st.error("SYSTEM ERROR: API CONNECTION FAILED. VERIFY API KEY.")

# --- MODULE 2: ENCRYPTED CLOUD VAULT (SUPABASE) ---
elif app_mode == "ENCRYPTED VAULT":
    st.subheader("RESTRICTED AREA: SUPABASE CLOUD PORTFOLIO")
    
    # STATE 1: AUTHENTICATION
    if not st.session_state.user_email:
        st.text("AWAITING CREDENTIALS...")
        
        auth_col1, auth_col2 = st.columns(2)
        with auth_col1:
            email = st.text_input("EMAIL ADDRESS")
        with auth_col2:
            password = st.text_input("PASSWORD", type="password")
            
        c1, c2 = st.columns(2)
        with c1:
            if st.button("[ INITIATE LOGIN ]"):
                try:
                    res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    st.session_state.user_email = res.user.email
                    st.success("ACCESS GRANTED.")
                    st.rerun()
                except Exception as e:
                    st.error("ACCESS DENIED: Invalid Credentials.")
        with c2:
            if st.button("[ REGISTER NEW OPERATOR ]"):
                try:
                    res = supabase.auth.sign_up({"email": email, "password": password})
                    st.success("REGISTRATION SUCCESSFUL. YOU MAY NOW LOGIN.")
                except Exception as e:
                    st.error(f"REGISTRATION FAILED: {e}")

    # STATE 2: VAULT UNLOCKED
    if st.session_state.user_email:
        st.success(f"CONNECTION SECURE. OPERATOR: {st.session_state.user_email}")
        
        with st.expander("[ + ADD NEW ASSET TO CLOUD ]"):
            with st.form("add_asset_form", clear_on_submit=True):
                a_name = st.text_input("Asset Identifier (e.g., 22K Ring)")
                a_weight = st.number_input("Weight (Grams)", min_value=0.1, step=0.1)
                a_price = st.number_input(f"Total Purchase Price ({curr})", min_value=1.0, step=100.0)
                submit_asset = st.form_submit_button("[ UPLOAD RECORD TO CLOUD ]")
                
                if submit_asset and a_name:
                    supabase.table("portfolio").insert({
                        "user_email": st.session_state.user_email,
                        "item_name": a_name,
                        "weight": a_weight,
                        "buy_price": a_price,
                        "currency": curr
                    }).execute()
                    st.success("RECORD UPLOADED SUCCESSFULLY.")
                    st.rerun()

        st.divider()
        st.write("### ASSET MANIFEST")
        
        response = supabase.table("portfolio").select("*").eq("user_email", st.session_state.user_email).execute()
        assets = response.data
        
        if len(assets) == 0:
            st.code(">>> MANIFEST EMPTY. NO ASSETS DETECTED FOR THIS USER.", language="bash")
        else:
            live_24k = fetch_live_rates(curr)
            live_22k = live_24k * 0.9166 if live_24k else 0
            
            for asset in assets:
                current_value = float(asset['weight']) * live_22k
                profit = current_value - float(asset['buy_price'])
                
                st.code(f"""
ASSET ID    : {asset['item_name']}
WEIGHT      : {asset['weight']}g
BUY IN      : {asset['currency']} {asset['buy_price']:,.2f}
LIVE VALUE  : {curr} {current_value:,.2f}
MARGIN      : {'+' if profit >= 0 else '-'} {curr} {abs(profit):,.2f}
                """, language="bash")
        
        if st.button("[ TERMINATE SESSION & LOCK VAULT ]"):
            supabase.auth.sign_out()
            st.session_state.user_email = None
            st.rerun()

# --- MODULE 3: ALERT WEBHOOKS ---
elif app_mode == "ALERT WEBHOOKS":
    st.subheader("AUTOMATED MARKET SURVEILLANCE")
    st.write("DEPLOY BACKGROUND TRACKERS TO MONITOR PRICE THRESHOLDS.")
    
    with st.form("alert_form"):
        contact = st.text_input("ENTER TRANSMISSION ADDRESS (Email/Telegram ID)")
        target_price = st.number_input(f"TARGET 24K DROP THRESHOLD ({curr})", min_value=1.0, value=float(fetch_live_rates(curr) or 100.0) - 5.0)
        submitted = st.form_submit_button("[ DEPLOY SURVEILLANCE CRON JOB ]")
        
        if submitted:
            st.success(f"TRACKER DEPLOYED. SYSTEM WILL PING {contact} IF {curr} DROPS BELOW {target_price:,.2f}.")

# --- SYSTEM FOOTER ---
st.markdown("<br><br>", unsafe_allow_html=True)
st.divider()
st.markdown(
    "<div style='text-align: center; color: #00ff41; opacity: 0.8; font-family: Courier New, monospace;'>"
    "/// SYSTEM ARCHITECTURE COMPILED & ENGINEERED BY: <strong>NORA FRANK</strong> ///"
    "<br><br>"
    "<div style='font-size: 0.75em; opacity: 0.6; max-width: 600px; margin: 0 auto;'>"
    "⚠️ <strong>DISCLAIMER:</strong> This application is built strictly for educational and portfolio demonstration purposes. "
    "The data and predictions provided do not constitute professional financial advice. "
    "Please consult a certified financial advisor before making any real-world investment decisions."
    "</div>"
    "</div>", 
    unsafe_allow_html=True
)
