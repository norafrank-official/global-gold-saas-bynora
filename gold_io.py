"""
gold_io.py
==========
All external I/O for the global-gold-saas app. The ONLY module that touches
the network, Streamlit secrets, Supabase, yfinance, or RSS feeds. Every other
module imports the helpers defined here so that retry / timeout / caching /
secret-handling logic lives in exactly one place.

Network surface:
    - GoldAPI.io     -> live spot rates (free tier: 50 calls/month; cached 1h)
    - Yahoo Finance  -> historical OHLC via yfinance (free; cached 6h)
    - Investing.com  -> commodity-metals RSS (free; cached 30m)
    - Supabase       -> auth + portfolio CRUD + watchlist CRUD
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

import feedparser
import pandas as pd
import requests
import streamlit as st
import yfinance as yf
from requests.adapters import HTTPAdapter
from supabase import Client, create_client
from urllib3.util.retry import Retry

from gold_engine import METALS_DB, is_valid_currency, is_valid_metal

# --------------------------------------------------------------------------- #
# LOGGING
# --------------------------------------------------------------------------- #

logger = logging.getLogger("gold")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s gold.%(funcName)s: %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


# --------------------------------------------------------------------------- #
# SECRETS  (only place that touches st.secrets)
# --------------------------------------------------------------------------- #

def _secret(key: str, default: str | None = None) -> str | None:
    try:
        return st.secrets[key]
    except Exception:
        return default


GOLD_API_KEY = _secret("GOLD_API_KEY")
SUPABASE_URL = _secret("SUPABASE_URL")
SUPABASE_KEY = _secret("SUPABASE_KEY")
NEWS_RSS_URL = _secret(
    "NEWS_RSS_URL",
    "https://www.investing.com/rss/commodities_Metals.rss",
)


# --------------------------------------------------------------------------- #
# HARDENED HTTP SESSION
# --------------------------------------------------------------------------- #

def _build_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    s.headers.update({"User-Agent": "global-gold-saas/2.0 (+https://streamlit.app)"})
    return s


_SESSION = _build_session()
_TIMEOUT = (3, 7)  # (connect, read) seconds


# --------------------------------------------------------------------------- #
# SUPABASE CLIENT
# --------------------------------------------------------------------------- #

@st.cache_resource
def get_supabase() -> Client | None:
    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.warning("Supabase credentials missing - VAULT module will be disabled")
        return None
    return create_client(SUPABASE_URL, SUPABASE_KEY)


# --------------------------------------------------------------------------- #
# LIVE RATES — GoldAPI
# --------------------------------------------------------------------------- #

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_live_rate(metal: str, currency: str) -> float | None:
    """
    Live 24K (or fine-purity) spot price per gram from GoldAPI.io.
    Returns None on any failure (logged, never silent).
    """
    if not is_valid_metal(metal):
        logger.warning("Rejected invalid metal code: %r", metal)
        return None
    if not is_valid_currency(currency):
        logger.warning("Rejected invalid currency code: %r", currency)
        return None
    if not GOLD_API_KEY:
        logger.warning("GOLD_API_KEY missing - live rate unavailable")
        return None

    url = f"https://www.goldapi.io/api/{metal}/{currency}"
    headers = {"x-access-token": GOLD_API_KEY, "Content-Type": "application/json"}

    try:
        r = _SESSION.get(url, headers=headers, timeout=_TIMEOUT)
    except requests.Timeout:
        logger.warning("GoldAPI timeout for %s/%s", metal, currency)
        return None
    except requests.ConnectionError:
        logger.warning("GoldAPI connection error for %s/%s", metal, currency)
        return None
    except requests.RequestException as e:
        logger.warning("GoldAPI request error: %s", e, exc_info=True)
        return None

    if r.status_code != 200:
        logger.warning("GoldAPI HTTP %d for %s/%s: %s", r.status_code, metal, currency, r.text[:200])
        return None

    try:
        return float(r.json().get("price_gram_24k"))
    except (ValueError, TypeError, KeyError) as e:
        logger.warning("GoldAPI JSON parse error: %s", e)
        return None


# --------------------------------------------------------------------------- #
# HISTORICAL DATA — yfinance
# --------------------------------------------------------------------------- #

_USD_BASED = "USD"


@st.cache_data(ttl=21_600, show_spinner=False)  # 6 hours
def fetch_history(metal: str, currency: str, days: int = 90) -> pd.DataFrame | None:
    """
    Pull `days` trading days of OHLC for `metal`, converted to `currency`.

    Returns a DataFrame with columns: open, high, low, close (lowercase)
    indexed by date. Returns None on failure.
    """
    if not is_valid_metal(metal):
        logger.warning("Rejected invalid metal code: %r", metal)
        return None
    if not is_valid_currency(currency):
        logger.warning("Rejected invalid currency code: %r", currency)
        return None

    ticker = METALS_DB[metal]["yf"]
    # Yahoo Finance only accepts specific period strings; map requested days to the
    # nearest valid bucket with enough headroom for non-trading days.
    period = "6mo" if days <= 90 else "1y"

    try:
        df = yf.download(ticker, period=period, interval="1d", auto_adjust=False, progress=False)
    except Exception as e:
        logger.warning("yfinance metal fetch failed for %s: %s", ticker, e, exc_info=True)
        return None

    if df is None or df.empty:
        logger.warning("yfinance returned empty frame for %s", ticker)
        return None

    df = _flatten_yf_frame(df)
    df = df.rename(columns=str.lower)
    needed = {"open", "high", "low", "close"}
    if not needed.issubset(df.columns):
        logger.warning("yfinance frame missing OHLC cols, got: %s", list(df.columns))
        return None

    df = df[["open", "high", "low", "close"]].dropna()

    # Currency conversion (futures are USD-denominated)
    if currency != _USD_BASED:
        rate = _fetch_fx_rate(currency, df.index)
        if rate is None:
            logger.warning("FX conversion unavailable for %s; returning USD series", currency)
        else:
            for col in ("open", "high", "low", "close"):
                df[col] = df[col] * rate

    df = df.tail(days)

    # XAG/XPT/XPD futures price in USD per troy ounce; GoldAPI returns price
    # per gram. We model the SERIES (relative moves) for ML — absolute level
    # doesn't have to match GoldAPI exactly, so we leave it in oz units.
    # The live rate from GoldAPI is the displayed "current price"; yfinance
    # provides the historical trajectory used to compute indicators.
    return df


def _flatten_yf_frame(df: pd.DataFrame) -> pd.DataFrame:
    """yfinance returns a MultiIndex column frame for some tickers — flatten it."""
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    return df


def _fetch_fx_rate(currency: str, dates: pd.DatetimeIndex) -> pd.Series | None:
    """
    Fetch USD->currency rate aligned to `dates` via yfinance.
    Yahoo FX tickers: '{CCY}=X' gives USD/CCY.
    """
    fx_ticker = f"{currency}=X"
    try:
        fx = yf.download(
            fx_ticker,
            start=dates.min().strftime("%Y-%m-%d"),
            end=(dates.max() + pd.Timedelta(days=2)).strftime("%Y-%m-%d"),
            interval="1d",
            auto_adjust=False,
            progress=False,
        )
    except Exception as e:
        logger.warning("FX fetch failed for %s: %s", fx_ticker, e)
        return None
    if fx is None or fx.empty:
        return None
    fx = _flatten_yf_frame(fx)
    if "Close" not in fx.columns:
        return None
    fx_close = fx["Close"].reindex(dates, method="ffill")
    return fx_close


# --------------------------------------------------------------------------- #
# NEWS RSS
# --------------------------------------------------------------------------- #

_TAG_RE = re.compile(r"<[^>]+>")


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_headlines(limit: int = 5) -> list[dict[str, str]]:
    """
    Returns latest commodity metals headlines as [{"title","link","published"}].
    Empty list on failure (logged).
    """
    try:
        r = _SESSION.get(NEWS_RSS_URL, timeout=_TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as e:
        logger.warning("RSS fetch failed: %s", e)
        return []

    try:
        parsed = feedparser.parse(r.content)
    except Exception as e:
        logger.warning("RSS parse failed: %s", e, exc_info=True)
        return []

    out: list[dict[str, str]] = []
    for entry in parsed.entries[:limit]:
        title = _TAG_RE.sub("", entry.get("title", "")).strip()
        link = entry.get("link", "")
        published = entry.get("published", "")[:16] or datetime.now().strftime("%Y-%m-%d")
        out.append({"title": title, "link": link, "published": published})
    return out


# --------------------------------------------------------------------------- #
# SUPABASE AUTH
# --------------------------------------------------------------------------- #

class AuthError(Exception):
    pass


def sign_in(email: str, password: str) -> str:
    sb = get_supabase()
    if sb is None:
        raise AuthError("Vault unavailable: Supabase not configured.")
    try:
        res = sb.auth.sign_in_with_password({"email": email, "password": password})
        if res.user is None or res.user.email is None:
            raise AuthError("Invalid credentials.")
        return res.user.email
    except AuthError:
        raise
    except Exception as e:
        logger.warning("sign_in failed for %s: %s", email, e)
        raise AuthError("Invalid credentials.") from e


def sign_up(email: str, password: str) -> None:
    sb = get_supabase()
    if sb is None:
        raise AuthError("Vault unavailable: Supabase not configured.")
    try:
        sb.auth.sign_up({"email": email, "password": password})
    except Exception as e:
        logger.warning("sign_up failed for %s: %s", email, e)
        raise AuthError(str(e)) from e


def sign_out() -> None:
    sb = get_supabase()
    if sb is None:
        return
    try:
        sb.auth.sign_out()
    except Exception as e:
        logger.warning("sign_out failed: %s", e)


# --------------------------------------------------------------------------- #
# PORTFOLIO CRUD
# --------------------------------------------------------------------------- #

@st.cache_data(ttl=60, show_spinner=False)
def list_portfolio(user_email: str) -> list[dict[str, Any]]:
    sb = get_supabase()
    if sb is None:
        return []
    try:
        res = sb.table("portfolio").select("*").eq("user_email", user_email).execute()
        return res.data or []
    except Exception as e:
        logger.warning("list_portfolio failed: %s", e, exc_info=True)
        return []


def add_asset(user_email: str, item_name: str, weight: float, buy_price: float, currency: str, metal: str = "XAU") -> bool:
    sb = get_supabase()
    if sb is None:
        return False
    try:
        sb.table("portfolio").insert(
            {
                "user_email": user_email,
                "item_name": item_name,
                "weight": float(weight),
                "buy_price": float(buy_price),
                "currency": currency,
            }
        ).execute()
        list_portfolio.clear()
        return True
    except Exception as e:
        logger.warning("add_asset failed: %s", e, exc_info=True)
        return False


def delete_asset(asset_id: int) -> bool:
    sb = get_supabase()
    if sb is None:
        return False
    try:
        sb.table("portfolio").delete().eq("id", asset_id).execute()
        list_portfolio.clear()
        return True
    except Exception as e:
        logger.warning("delete_asset failed: %s", e, exc_info=True)
        return False


# --------------------------------------------------------------------------- #
# WATCHLIST CRUD
# --------------------------------------------------------------------------- #

@st.cache_data(ttl=60, show_spinner=False)
def list_watchlist(user_email: str) -> list[dict[str, Any]]:
    sb = get_supabase()
    if sb is None:
        return []
    try:
        res = sb.table("watchlist").select("*").eq("user_email", user_email).execute()
        return res.data or []
    except Exception as e:
        logger.warning("list_watchlist failed: %s", e, exc_info=True)
        return []


def add_watch(user_email: str, metal: str, currency: str, target_price: float, direction: str) -> bool:
    sb = get_supabase()
    if sb is None:
        return False
    if direction not in ("above", "below"):
        logger.warning("invalid watchlist direction: %r", direction)
        return False
    try:
        sb.table("watchlist").insert(
            {
                "user_email": user_email,
                "metal": metal,
                "currency": currency,
                "target_price": float(target_price),
                "direction": direction,
            }
        ).execute()
        list_watchlist.clear()
        return True
    except Exception as e:
        logger.warning("add_watch failed: %s", e, exc_info=True)
        return False


def delete_watch(watch_id: int) -> bool:
    sb = get_supabase()
    if sb is None:
        return False
    try:
        sb.table("watchlist").delete().eq("id", watch_id).execute()
        list_watchlist.clear()
        return True
    except Exception as e:
        logger.warning("delete_watch failed: %s", e, exc_info=True)
        return False
