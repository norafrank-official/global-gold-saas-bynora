import streamlit as st
import requests
import numpy as np
from sklearn.linear_model import LinearRegression
import plotly.graph_objects as go
from datetime import datetime, timedelta
from fpdf import FPDF
import urllib.parse
import hashlib
from supabase import create_client, Client

# --- CONFIGURATION & STYLING ---
st.set_page_config(page_title="Global Asset Command Center", layout="wide")

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

# --- CLOUD INITIALIZATION ---
API_KEY = st.secrets["goldapi-341131eeaa93df79ea13bd94e65995b6-io"]
SUPABASE_URL = st.secrets["https://qgnpnuahtkgevsgvwunp.supabase.co"]
SUPABASE_KEY = st.secrets["sb_publishable_35shkWExhbhx47YXiEZnZQ_wcC_EBIP"]

@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase: Client = init_supabase()

def hash_pin(pin):
    return hashlib.sha256(pin.encode()).hexdigest()

# --- GLOBAL MARKET DATABASE ---
MARKET_DB = {
    "India": {"curr": "INR", "sym": "INR", "tax_type": "SPLIT", "gold_tax": 0.03, "make_tax": 0.05},
    "Saudi Arabia": {"curr": "SAR", "sym": "SAR", "tax_type": "FLAT", "tax_rate": 0.15},
    "United Arab Emirates": {"curr": "AED", "sym": "AED", "tax_type": "FLAT", "tax_rate": 0.05},
    "United States": {"curr": "USD", "sym": "$", "tax_type": "FLAT", "tax_rate": 0.00},
    "United Kingdom": {"curr": "GBP", "sym": "£", "tax_type": "FLAT", "tax_rate": 0.20},
    "Global Standard": {"curr": "USD", "sym": "$", "tax_type": "FLAT", "tax_rate": 0.00}
}

# --- SYSTEM STATE ---
if 'vault_unlocked' not in st.session_state:
    st.session_state.vault_unlocked = False
if 'active_user' not in st.session_state:
    st.session_state.active_user = None
if 'geo_location' not in st.session_state:
    st.session_state.geo_location = None

query_params = st.query_params
url_weight = float(query_params.get("weight", 8.0))
url_making = float(query_params.get("making", 12.0))
url_market = query_params.get("market", None)

# --- CORE FUNCTIONS ---
def get_geo_location():
    if not st.session_state.geo_location:
        try:
            res = requests.get('http://ip-api.com/json/', timeout=3).json()
            st.session_state.geo_location = res.get('country', 'Global Standard')
        except:
            st.session_state.geo_location = 'Global Standard'
    return st.session_state.geo_location

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
    
    pdf.set_font("Courier", style="I will walk you through the **Supabase Cloud Database** setup. Since you are building a professional SaaS portfolio piece, Supabase is the absolute best choice. It gives you a true PostgreSQL cloud database and handles all the password encryption (authentication) for you behind the scenes. 

Here is the exact protocol to rip out the local SQLite database and wire your Command Center up to the cloud.

### Phase 1: Set Up the Supabase Server
1. Go to **[Supabase.com](https://supabase.com/)** and sign in with your GitHub account.
2. Click **"New Project"**, name it `AssetCommandCenter`, and create a strong database password (save this, but we won't need it for the code).
3. Wait about 2 minutes for the database to provision.
4. On your dashboard, go to **Project Settings** (the gear icon) -> **API**. 
5. Copy your **Project URL** and your **`anon` `public` API Key**. You will need these for Streamlit.

### Phase 2: Build the Cloud Table
We need to tell Supabase how to store your gold assets.
1. On the left menu, click **SQL Editor**.
2. Click **"New Query"**, paste the following SQL command, and hit **Run**:

```sql
CREATE TABLE portfolio (
  id bigint generated by default as identity primary key,
  user_email text not null,
  item_name text not null,
  weight numeric not null,
  buy_price numeric not null,
  currency text not null,
  created_at timestamp with time zone default timezone('utc'::text, now()) not null
);
