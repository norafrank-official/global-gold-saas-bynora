"""
updatedgold.py
==============
global-gold-saas v2 — Streamlit UI + routing.

This module owns ONLY the presentation layer:
    - Page config + brutalist CSS theme
    - Sidebar navigation (metal / region / module selectors)
    - Three modules: MARKET TERMINAL, ENCRYPTED VAULT, ALERT WEBHOOKS
    - Header + footer

All logic lives in `gold_engine.py` (pure functions); all external I/O lives
in `gold_io.py` (network, Supabase, secrets).
"""

from __future__ import annotations

import urllib.parse
from datetime import datetime, timedelta

import plotly.graph_objects as go
import streamlit as st

import gold_engine as eng
import gold_io as io_

# --------------------------------------------------------------------------- #
# PAGE CONFIG + THEME
# --------------------------------------------------------------------------- #

st.set_page_config(page_title="Gold Portfolio Tracker", layout="wide")

st.markdown(
    """
    <style>
    .main { background-color: #0e1117; color: #00ff41; font-family: 'Courier New', monospace; }
    div[data-testid="stMetricValue"], div[data-testid="stMarkdownContainer"] p { color: #00ff41 !important; }
    h1, h2, h3, h4, span { color: #00ff41 !important; }
    .stButton>button { border: 1px solid #00ff41; color: #00ff41; background-color: black; width: 100%; }
    .stButton>button:hover { background-color: #00ff41; color: black; }
    .stTextInput>div>div>input, .stNumberInput>div>div>input { color: #00ff41; background-color: #262730; border: 1px solid #00ff41; }
    .signal-buy   { color: #00ff41; font-weight: bold; }
    .signal-sell  { color: #ff003c; font-weight: bold; }
    .signal-hold  { color: #ffaa00; font-weight: bold; }
    </style>
    """,
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------- #
# SESSION STATE
# --------------------------------------------------------------------------- #

if "user_email" not in st.session_state:
    st.session_state.user_email = None

query_params = st.query_params
url_weight = float(query_params.get("weight", 8.0) or 8.0)
url_making = float(query_params.get("making", 12.0) or 12.0)
url_market = query_params.get("market", None)
url_metal = query_params.get("metal", None)

# --------------------------------------------------------------------------- #
# HEADER
# --------------------------------------------------------------------------- #

detected_country = "India"  # cloud proxy bypass — geo-IP optional, out of scope
default_market = url_market if (url_market and url_market in eng.MARKET_DB) else detected_country

st.title("GOLD PORTFOLIO TRACKER")
st.text(f"SYSTEM STATUS: ONLINE | GEO-TRACE LOCATION: {detected_country}")
st.divider()

# --------------------------------------------------------------------------- #
# SIDEBAR
# --------------------------------------------------------------------------- #

with st.sidebar:
    st.header("SYSTEM MODULE")
    app_mode = st.radio(
        "SELECT PROTOCOL",
        ["MARKET TERMINAL", "ENCRYPTED VAULT", "ALERT WEBHOOKS"],
    )
    st.divider()

    st.header("ASSET")
    metal_codes = list(eng.METALS_DB.keys())
    metal_labels = [eng.METALS_DB[c]["name"] for c in metal_codes]
    default_metal_idx = metal_codes.index(url_metal) if url_metal in metal_codes else 0
    selected_metal_idx = st.selectbox(
        "SELECT METAL",
        range(len(metal_codes)),
        index=default_metal_idx,
        format_func=lambda i: f"{metal_codes[i]} - {metal_labels[i]}",
    )
    selected_metal = metal_codes[selected_metal_idx]
    metal_cfg = eng.METALS_DB[selected_metal]

    purity_options = list(metal_cfg["purities"].keys())
    purity_default_idx = purity_options.index(metal_cfg["default_purity"])
    selected_purity = st.selectbox("SELECT PURITY", purity_options, index=purity_default_idx)
    purity_factor = metal_cfg["purities"][selected_purity]

    st.divider()
    st.header("MARKET OVERRIDE")
    market_keys = list(eng.MARKET_DB.keys())
    default_index = market_keys.index(default_market)
    selected_market = st.selectbox("SELECT REGION", market_keys, index=default_index)

    market_data = eng.MARKET_DB[selected_market]
    curr = market_data["curr"]
    symbol = market_data["sym"]

# --------------------------------------------------------------------------- #
# HELPERS
# --------------------------------------------------------------------------- #

def _render_news_strip() -> None:
    headlines = io_.fetch_headlines(limit=5)
    if not headlines:
        st.code(">>> NEWS WIRE OFFLINE.", language="bash")
        return
    lines = [f"[{h['published']}] {h['title']}" for h in headlines]
    st.code(">>> COMMODITY METALS NEWS\n" + "\n".join(lines), language="bash")


def _render_signal_panel(spot: float, metal: str, currency: str) -> None:
    history = io_.fetch_history(metal, currency, days=120)
    if history is None or len(history) < 30:
        st.warning(
            f"INSUFFICIENT MARKET HISTORY FOR {metal}/{currency} - "
            "DECISION ENGINE OFFLINE (NEED >=30 TRADING DAYS)."
        )
        return

    indicators = eng.compute_indicators(history)
    prediction, lower, upper = eng.forecast_ensemble(history, indicators)
    signal = eng.decide_signal(spot, indicators, prediction)
    wins, decisions = eng.backtest_walkforward(history, lookback=30)

    css_class = {"BUY": "signal-buy", "SELL": "signal-sell", "HOLD": "signal-hold"}[signal.action]
    st.markdown(
        f"<h3 class='{css_class}'>&gt;&gt;&gt; SIGNAL: {signal.action} "
        f"[CONF: {signal.confidence:.2f} | SCORE: {signal.score:+d}]</h3>",
        unsafe_allow_html=True,
    )

    win_rate_str = (
        f"WIN RATE (30D BACKTEST): {wins}/{decisions} ({wins/decisions*100:.0f}%)"
        if decisions
        else "WIN RATE (30D BACKTEST): N/A (TOO FEW DECISIONS)"
    )
    st.caption(win_rate_str)

    breakdown_lines = [
        f"{b.label:<12}  {'+' if b.vote > 0 else '-' if b.vote < 0 else ' '}  {b.detail}"
        for b in signal.breakdown
    ]
    st.code(">>> INDICATOR BREAKDOWN\n" + "\n".join(breakdown_lines), language="bash")

    # Chart: historical close + SMA overlays + forecast point with CI ribbon
    dates = history.index.strftime("%b %d").tolist()
    close = history["close"].astype(float).tolist()
    sma7 = indicators["sma_7"].tolist()
    sma30 = indicators["sma_30"].tolist()

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dates, y=close, mode="lines", name="CLOSE", line=dict(color="#00ff41", width=2)))
    fig.add_trace(go.Scatter(x=dates, y=sma7, mode="lines", name="SMA(7)", line=dict(color="#00aaff", width=1)))
    fig.add_trace(go.Scatter(x=dates, y=sma30, mode="lines", name="SMA(30)", line=dict(color="#ffaa00", width=1)))

    tomorrow = "T+1"
    fig.add_trace(
        go.Scatter(
            x=[dates[-1], tomorrow],
            y=[close[-1], prediction],
            mode="lines+markers",
            name="FORECAST",
            line=dict(color="#ff003c", width=2, dash="dot"),
        )
    )
    # Confidence interval shading at the forecast point
    fig.add_trace(
        go.Scatter(
            x=[tomorrow, tomorrow],
            y=[lower, upper],
            mode="lines",
            name="95% CI",
            line=dict(color="#ff003c", width=8),
            opacity=0.3,
        )
    )
    fig.update_layout(
        plot_bgcolor="#0e1117",
        paper_bgcolor="#0e1117",
        font=dict(color="#00ff41", family="Courier New"),
        margin=dict(l=0, r=0, t=10, b=0),
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=True, gridcolor="#262730"),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    st.plotly_chart(fig, use_container_width=True)


# --------------------------------------------------------------------------- #
# MODULE 1: MARKET TERMINAL
# --------------------------------------------------------------------------- #

if app_mode == "MARKET TERMINAL":
    spot_24k = io_.fetch_live_rate(selected_metal, curr)

    if spot_24k is None:
        st.error("SYSTEM ERROR: API CONNECTION FAILED OR QUOTA EXHAUSTED. VERIFY GOLD_API_KEY.")
    else:
        rate_purity = spot_24k * purity_factor

        c1, c2, c3 = st.columns(3)
        c1.metric(
            f"LIVE {selected_purity} (1G) - {curr}",
            f"{symbol}{rate_purity:,.2f}",
        )
        c2.metric(
            f"LIVE {selected_purity} (8G/PAVAN)",
            f"{symbol}{(rate_purity * 8):,.2f}",
        )
        c3.metric(
            "FINE SPOT RATE (1G)",
            f"{symbol}{spot_24k:,.2f}",
        )

        _render_news_strip()

        st.divider()
        st.subheader(f"AI DECISION ENGINE - {metal_cfg['name']}")
        _render_signal_panel(spot_24k, selected_metal, curr)

        st.divider()
        st.subheader("PROCUREMENT ENGINE")
        col_input, col_result = st.columns(2)

        with col_input:
            weight = st.number_input("Weight (Grams)", min_value=0.1, max_value=100_000.0, value=url_weight)
            m_type = st.selectbox("Making Charge Type", ["Percentage", "Flat Rate"])
            m_val = st.number_input(f"Enter {m_type} Value", min_value=0.0, value=url_making)

        pricing = eng.compute_pricing(
            rate_per_gram=spot_24k,
            weight=weight,
            purity_factor=purity_factor,
            making_type=m_type,
            making_value=m_val,
            market_key=selected_market,
        )

        with col_result:
            st.write(f"BASE METAL VALUE: {symbol}{pricing.metal_value:,.2f}")
            st.write(f"LABOR CHARGES:    {symbol}{pricing.making_cost:,.2f}")
            st.caption(pricing.tax_breakdown)
            st.write(f"### NET PAYABLE: {symbol}{pricing.total:,.2f}")

            base_url = "https://your-app-name.streamlit.app/"
            query_str = urllib.parse.urlencode(
                {
                    "weight": weight,
                    "making": m_val,
                    "market": selected_market,
                    "metal": selected_metal,
                }
            )
            st.code(f"SECURE TRANSMISSION LINK:\n{base_url}?{query_str}", language="bash")

            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            pdf_data = eng.create_pdf_report(
                metal_name=metal_cfg["name"],
                purity_label=selected_purity,
                purity_factor=purity_factor,
                market=selected_market,
                currency=curr,
                weight=weight,
                rate_per_gram=spot_24k,
                pricing=pricing,
                timestamp=current_time,
            )
            st.download_button(
                label="[ DOWNLOAD FINANCIAL REPORT .PDF ]",
                data=pdf_data,
                file_name=f"Quote_{selected_metal}_{curr}_{datetime.now().strftime('%Y%m%d')}.pdf",
                mime="application/pdf",
            )

# --------------------------------------------------------------------------- #
# MODULE 2: ENCRYPTED VAULT (Supabase: auth + portfolio + watchlist)
# --------------------------------------------------------------------------- #

elif app_mode == "ENCRYPTED VAULT":
    st.subheader("RESTRICTED AREA: SUPABASE CLOUD PORTFOLIO")

    # STATE 1: AUTH
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
                if not eng.is_valid_email(email):
                    st.error("ACCESS DENIED: Invalid email format.")
                elif len(password) < 6:
                    st.error("ACCESS DENIED: Password too short.")
                else:
                    try:
                        st.session_state.user_email = io_.sign_in(email, password)
                        st.success("ACCESS GRANTED.")
                        st.rerun()
                    except io_.AuthError as e:
                        st.error(f"ACCESS DENIED: {e}")
        with c2:
            if st.button("[ REGISTER NEW OPERATOR ]"):
                if not eng.is_valid_email(email):
                    st.error("REGISTRATION FAILED: Invalid email format.")
                elif len(password) < 6:
                    st.error("REGISTRATION FAILED: Password must be at least 6 chars.")
                else:
                    try:
                        io_.sign_up(email, password)
                        st.success("REGISTRATION SUCCESSFUL. CHECK YOUR EMAIL TO CONFIRM, THEN LOGIN.")
                    except io_.AuthError as e:
                        st.error(f"REGISTRATION FAILED: {e}")

    # STATE 2: UNLOCKED
    if st.session_state.user_email:
        user_email = st.session_state.user_email
        st.success(f"CONNECTION SECURE. OPERATOR: {user_email}")

        # --- Portfolio: add asset ---
        with st.expander("[ + ADD NEW ASSET TO CLOUD ]"):
            with st.form("add_asset_form", clear_on_submit=True):
                a_name = st.text_input("Asset Identifier (e.g., 22K Ring)")
                a_weight = st.number_input("Weight (Grams)", min_value=0.1, max_value=100_000.0, step=0.1)
                a_price = st.number_input(f"Total Purchase Price ({curr})", min_value=1.0, step=100.0)
                if st.form_submit_button("[ UPLOAD RECORD TO CLOUD ]"):
                    if a_name and eng.is_valid_weight(a_weight):
                        ok = io_.add_asset(user_email, a_name.strip(), a_weight, a_price, curr, selected_metal)
                        if ok:
                            st.success("RECORD UPLOADED SUCCESSFULLY.")
                            st.rerun()
                        else:
                            st.error("UPLOAD FAILED. CHECK LOGS.")
                    else:
                        st.error("INVALID ASSET DATA.")

        st.divider()
        st.write("### ASSET MANIFEST")

        assets = io_.list_portfolio(user_email)
        if not assets:
            st.code(">>> MANIFEST EMPTY. NO ASSETS DETECTED FOR THIS USER.", language="bash")
        else:
            live_spot = io_.fetch_live_rate(selected_metal, curr)
            live_priced = live_spot * purity_factor if live_spot else 0.0
            for asset in assets:
                current_value = float(asset["weight"]) * live_priced
                profit = current_value - float(asset["buy_price"])
                cols = st.columns([5, 1])
                with cols[0]:
                    st.code(
                        f"""
ASSET ID    : {asset['item_name']}
WEIGHT      : {asset['weight']}g
BUY IN      : {asset['currency']} {float(asset['buy_price']):,.2f}
LIVE VALUE  : {curr} {current_value:,.2f}  ({selected_purity} basis)
MARGIN      : {'+' if profit >= 0 else '-'} {curr} {abs(profit):,.2f}
""".strip(),
                        language="bash",
                    )
                with cols[1]:
                    if st.button("[ DELETE ]", key=f"del_asset_{asset['id']}"):
                        if io_.delete_asset(asset["id"]):
                            st.rerun()

        # --- Watchlist ---
        st.divider()
        st.write("### TARGET WATCHLIST")

        with st.expander("[ + ADD PRICE TARGET ]"):
            with st.form("add_watch_form", clear_on_submit=True):
                w_metal = st.selectbox(
                    "METAL",
                    metal_codes,
                    format_func=lambda c: f"{c} - {eng.METALS_DB[c]['name']}",
                )
                w_direction = st.selectbox("DIRECTION", ["below", "above"])
                w_target = st.number_input(f"TARGET PRICE ({curr})", min_value=0.01, step=1.0)
                if st.form_submit_button("[ ARM TARGET ]"):
                    if io_.add_watch(user_email, w_metal, curr, w_target, w_direction):
                        st.success("TARGET ARMED.")
                        st.rerun()
                    else:
                        st.error("FAILED TO ARM TARGET.")

        watches = io_.list_watchlist(user_email)
        if not watches:
            st.code(">>> NO ACTIVE TARGETS.", language="bash")
        else:
            for w in watches:
                live = io_.fetch_live_rate(w["metal"], w["currency"])
                status = "PENDING"
                if live is not None:
                    if w["direction"] == "below" and live <= float(w["target_price"]):
                        status = "TRIGGERED"
                    elif w["direction"] == "above" and live >= float(w["target_price"]):
                        status = "TRIGGERED"
                live_str = f"{w['currency']} {live:,.2f}" if live is not None else "N/A"
                cols = st.columns([5, 1])
                with cols[0]:
                    st.code(
                        f"""
METAL       : {w['metal']} ({eng.METALS_DB.get(w['metal'], {'name': '?'})['name']})
DIRECTION   : {w['direction'].upper()}
TARGET      : {w['currency']} {float(w['target_price']):,.2f}
LIVE        : {live_str}
STATUS      : {status}
""".strip(),
                        language="bash",
                    )
                with cols[1]:
                    if st.button("[ DELETE ]", key=f"del_watch_{w['id']}"):
                        if io_.delete_watch(w["id"]):
                            st.rerun()

        st.divider()
        if st.button("[ TERMINATE SESSION & LOCK VAULT ]"):
            io_.sign_out()
            st.session_state.user_email = None
            st.rerun()

# --------------------------------------------------------------------------- #
# MODULE 3: ALERT WEBHOOKS (stub preserved — wiring is future scope)
# --------------------------------------------------------------------------- #

elif app_mode == "ALERT WEBHOOKS":
    st.subheader("AUTOMATED MARKET SURVEILLANCE")
    st.write("DEPLOY BACKGROUND TRACKERS TO MONITOR PRICE THRESHOLDS.")
    st.caption(
        "Note: webhook firing requires an out-of-process worker. "
        "Use the WATCHLIST under VAULT for immediate target monitoring during your session."
    )

    with st.form("alert_form"):
        contact = st.text_input("ENTER TRANSMISSION ADDRESS (Email/Telegram ID)")
        live = io_.fetch_live_rate(selected_metal, curr) or 100.0
        target_price = st.number_input(
            f"TARGET {selected_metal} DROP THRESHOLD ({curr})",
            min_value=1.0,
            value=max(live - 5.0, 1.0),
        )
        if st.form_submit_button("[ DEPLOY SURVEILLANCE CRON JOB ]"):
            if contact and (eng.is_valid_email(contact) or contact.startswith("@") or contact.isdigit()):
                st.success(
                    f"TRACKER REGISTERED. SYSTEM WILL PING {contact} "
                    f"IF {selected_metal}/{curr} DROPS BELOW {target_price:,.2f}."
                )
            else:
                st.error("INVALID TRANSMISSION ADDRESS.")

# --------------------------------------------------------------------------- #
# FOOTER
# --------------------------------------------------------------------------- #

st.markdown("<br><br>", unsafe_allow_html=True)
st.divider()
st.markdown(
    "<div style='text-align: center; color: #00ff41; opacity: 0.8; font-family: Courier New, monospace;'>"
    "/// SYSTEM ARCHITECTURE COMPILED & ENGINEERED BY: <strong>NORA FRANK</strong> ///"
    "<br><br>"
    "<div style='font-size: 0.75em; opacity: 0.6; max-width: 600px; margin: 0 auto;'>"
    "<strong>DISCLAIMER:</strong> This application is built strictly for educational and portfolio demonstration purposes. "
    "The data and predictions provided do not constitute professional financial advice. "
    "Please consult a certified financial advisor before making any real-world investment decisions."
    "</div>"
    "</div>",
    unsafe_allow_html=True,
)
