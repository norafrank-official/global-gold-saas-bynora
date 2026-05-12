# global-gold-saas-bynora

A brutalist, terminal-inspired fintech web application for real-time global precious-metal analytics, an AI BUY/SELL/HOLD decision engine, and secure portfolio management.

![System Status](https://img.shields.io/badge/System-Online-00ff41?style=for-the-badge&logoColor=black)
![Python](https://img.shields.io/badge/Python-3.10+-black?style=for-the-badge&logo=python&logoColor=00ff41)
![Streamlit](https://img.shields.io/badge/Streamlit-Framework-black?style=for-the-badge&logo=streamlit&logoColor=00ff41)
![Supabase](https://img.shields.io/badge/Supabase-Cloud_DB-black?style=for-the-badge&logo=supabase&logoColor=00ff41)
![Free Tier](https://img.shields.io/badge/Cost-$0%2Fmonth-00ff41?style=for-the-badge)

---

## What's New in v2

* **AI Decision Engine** — replaces the old single-LinearRegression bullish/bearish badge with a 5-signal voting system (RSI / MACD / SMA-trend / Bollinger / forecast) that outputs a confidence-scored **BUY · SELL · HOLD** with per-indicator rationale and a 30-day walk-forward backtest win rate.
* **Multi-Metal** — Gold (XAU), Silver (XAG), Platinum (XPT), Palladium (XPD), each with metal-specific purity dropdowns (24K/22K/18K, 999/925, 950/900).
* **Real Historical Data** — `yfinance` pulls live futures history (`GC=F`, `SI=F`, `PL=F`, `PA=F`) — no more synthetic random-walk training.
* **Ensemble Forecaster** — LinearRegression + RandomForest + GradientBoosting averaged, with 95% confidence interval ribbon on the chart.
* **Commodity News Wire** — top-5 dated metal headlines via free Investing.com RSS.
* **Watchlist** — per-user price targets stored in Supabase with `above`/`below` triggers.
* **Portfolio Delete** — finally; old version only supported add/list.
* **Hardened Network Surface** — `requests.Session` with retry + timeout, aggressive caching, specific exception handling (no more bare `except:` swallowing errors).
* **Modular Architecture** — single 327-line file split into UI / pure-logic / I/O layers per the project's DevSecOps principles.

---

## System Overview

A full-stack SaaS application that breaks away from cluttered financial dashboards. Distraction-free, brutalist terminal UI for tracking multi-metal markets, forecasting trends with a real ML decision engine, and securely managing personal assets in the cloud.

## Free-Tier Cost Audit — $0/month total

| Service | Tier | Limit |
|---|---|---|
| Streamlit Community Cloud | Free public | Unlimited public apps |
| Supabase | Free | 500 MB DB · 50K MAU · auto-pause after 1 wk idle |
| GoldAPI.io | Free | 50 calls/month — protected by 1h cache |
| yfinance | Open-source | Unlimited Yahoo Finance pulls |
| Investing.com RSS | Free public | No auth, no limits |

---

## Architecture (3 modules, strict separation)

```
.
├── updatedgold.py     # Streamlit UI + routing only — no logic, no I/O
├── gold_engine.py     # Pure logic: indicators, ensemble forecaster,
│                      # signal voting, backtest, pricing, PDF, validators
├── gold_io.py         # All external I/O: GoldAPI · yfinance · Supabase ·
│                      # RSS · retry/timeout/caching/logging — the ONLY
│                      # module that touches st.secrets
├── schema.sql         # One-time Supabase migration (watchlist table + RLS)
├── .env.example       # Secret template
└── requirements.txt   # Pinned dependencies
```

**Data flow:**
```
yfinance(GC=F) ──► gold_engine.compute_indicators ──┐
                                                     ├──► gold_engine.decide_signal ──► BUY/SELL/HOLD
                                                     │    (RSI · MACD · SMA · BB · forecast vote)
sklearn ensemble (LinReg + RF + GBR) ───────────────┘
GoldAPI ──► live spot rate ──► live UI metrics + PDF quotation
Supabase ──► auth · portfolio · watchlist
```

---

## Technology Stack

* **Frontend** — Streamlit + Plotly · brutalist `#0e1117` background, `#00ff41` terminal-green primary, Courier monospace
* **Backend** — Supabase Postgres (auth · portfolio · watchlist) with row-level security
* **Machine Learning** — scikit-learn (LinearRegression + RandomForest + GradientBoosting ensemble) · pure numpy/pandas indicators
* **External Data** — GoldAPI.io (live spot) · yfinance (historical OHLC) · Investing.com RSS (news)
* **PDF** — fpdf2 (UTF-8 safe)

---

## Setup

### 1. Clone

```bash
git clone https://github.com/norafrank-official/global-gold-saas-bynora.git
cd global-gold-saas-bynora
```

### 2. Python environment

```bash
python -m venv .venv
# Windows:
.\.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Supabase migration (one-time)

Open your Supabase project dashboard → **SQL Editor** → paste the contents of [`schema.sql`](schema.sql) → **Run**. This creates the `watchlist` table with row-level security policies.

The existing `portfolio` table is untouched. (Audit-flag in `schema.sql`: ensure equivalent RLS is enabled on `portfolio` as well.)

### 4. Secrets

Local dev: create `.streamlit/secrets.toml`:

```toml
GOLD_API_KEY = "goldapi-xxxxxxxxxxxxxxxxxx"
SUPABASE_URL = "https://YOUR_PROJECT_REF.supabase.co"
SUPABASE_KEY = "YOUR_PROJECT_ANON_PUBLIC_KEY"
```

Streamlit Cloud: paste the same TOML into **App Settings → Secrets**.

The `.streamlit/secrets.toml` file is git-ignored — never commit real keys. See [`.env.example`](.env.example) for the full template.

### 5. Run

```bash
streamlit run updatedgold.py
```

---

## The Decision Engine

The headline upgrade. Instead of "bullish or bearish," the app now combines five independent signals into a transparent voting score:

| Signal | Trigger | Vote |
|---|---|---|
| **RSI(14)** | < 30 oversold / > 70 overbought | ±1 |
| **MACD** | line vs signal crossover | ±1 |
| **SMA trend** | SMA(7) vs SMA(30) | ±1 |
| **Bollinger** | price outside ±2σ envelope | ±1 |
| **Forecast** | ensemble prediction > ±0.5% move | ±1 |

```
score >= +2 ──► BUY
score <= -2 ──► SELL
otherwise   ──► HOLD
```

A 30-day walk-forward backtest replays the engine on real history and shows the win rate — so the model is never a black box.

---

## Security & DevSecOps Posture

* No hardcoded secrets — everything via `st.secrets` (centralised in `gold_io.py`)
* `requests.Session` with `urllib3.Retry` (3 retries, exponential backoff, 429/5xx) and `(3s, 7s)` connect/read timeouts
* Input validation: email regex · currency allow-list · weight bounds before any API call
* Row-level security on Supabase `watchlist` (per-user JWT email match)
* Specific exception handling with `logger.warning(..., exc_info=True)` — no bare `except:` swallowing failures
* Aggressive caching protects GoldAPI's 50/month free quota

---

## Disclaimer

This application is built strictly for educational and portfolio demonstration purposes. Data and AI signals do not constitute professional financial advice. Consult a certified financial advisor before any real-world investment decision.

---

## Author

**Nora Frank** — Software Developer · Cybersecurity Enthusiast · Real-Time Systems Builder
