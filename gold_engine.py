"""
gold_engine.py
==============
Pure business logic for the global-gold-saas app. No network, no Streamlit,
no Supabase — every function in this module is deterministic and unit-testable
in isolation.

Responsibilities:
    - METALS_DB / MARKET_DB config
    - Technical indicators (SMA, EMA, MACD, RSI, Bollinger, ATR)
    - Ensemble forecaster (LinearRegression + RandomForest + GradientBoosting)
    - BUY / SELL / HOLD signal voting engine
    - Walk-forward backtest
    - Procurement pricing math (purity / making / tax)
    - PDF report generation
    - Input validators
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import numpy as np
import pandas as pd
from fpdf import FPDF
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression

# --------------------------------------------------------------------------- #
# CONFIG
# --------------------------------------------------------------------------- #

METALS_DB: dict[str, dict] = {
    "XAU": {
        "name": "GOLD",
        "yf": "GC=F",
        "purities": {"24K": 1.0, "22K": 0.9166, "18K": 0.75},
        "default_purity": "22K",
    },
    "XAG": {
        "name": "SILVER",
        "yf": "SI=F",
        "purities": {"999": 0.999, "925": 0.925},
        "default_purity": "999",
    },
    "XPT": {
        "name": "PLATINUM",
        "yf": "PL=F",
        "purities": {"950": 0.95, "900": 0.90},
        "default_purity": "950",
    },
    "XPD": {
        "name": "PALLADIUM",
        "yf": "PA=F",
        "purities": {"999": 0.999, "950": 0.95},
        "default_purity": "999",
    },
}

MARKET_DB: dict[str, dict] = {
    "India":                {"curr": "INR", "sym": "Rs ",  "tax_type": "SPLIT", "gold_tax": 0.03, "make_tax": 0.05},
    "Saudi Arabia":         {"curr": "SAR", "sym": "SAR ", "tax_type": "FLAT",  "tax_rate": 0.15},
    "United Arab Emirates": {"curr": "AED", "sym": "AED ", "tax_type": "FLAT",  "tax_rate": 0.05},
    "United States":        {"curr": "USD", "sym": "$",    "tax_type": "FLAT",  "tax_rate": 0.00},
    "United Kingdom":       {"curr": "GBP", "sym": "GBP ", "tax_type": "FLAT",  "tax_rate": 0.20},
    "Global Standard":      {"curr": "USD", "sym": "$",    "tax_type": "FLAT",  "tax_rate": 0.00},
}

ALLOWED_CURRENCIES = {m["curr"] for m in MARKET_DB.values()}

# --------------------------------------------------------------------------- #
# VALIDATORS
# --------------------------------------------------------------------------- #

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(value: str) -> bool:
    return isinstance(value, str) and bool(_EMAIL_RE.match(value.strip()))


def is_valid_currency(code: str) -> bool:
    return isinstance(code, str) and code in ALLOWED_CURRENCIES


def is_valid_weight(weight: float) -> bool:
    try:
        w = float(weight)
    except (TypeError, ValueError):
        return False
    return 0.1 <= w <= 100_000.0


def is_valid_metal(code: str) -> bool:
    return code in METALS_DB


# --------------------------------------------------------------------------- #
# INDICATORS
# --------------------------------------------------------------------------- #

def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal_span: int = 9) -> tuple[pd.Series, pd.Series]:
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal_span)
    return macd_line, signal_line


def bollinger(series: pd.Series, window: int = 20, num_std: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = sma(series, window)
    std = series.rolling(window=window, min_periods=window).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return lower, mid, upper


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def compute_indicators(history: pd.DataFrame) -> dict:
    """
    history columns expected: open, high, low, close (lowercase).
    Returns a dict of indicator series + latest scalar values.
    """
    close = history["close"]
    macd_line, signal_line = macd(close)
    bb_lower, bb_mid, bb_upper = bollinger(close)

    out = {
        "sma_7": sma(close, 7),
        "sma_30": sma(close, 30),
        "ema_12": ema(close, 12),
        "ema_26": ema(close, 26),
        "macd": macd_line,
        "macd_signal": signal_line,
        "rsi_14": rsi(close, 14),
        "bb_lower": bb_lower,
        "bb_mid": bb_mid,
        "bb_upper": bb_upper,
        "atr_14": atr(history["high"], history["low"], close, 14),
    }

    latest = {k: (float(v.iloc[-1]) if not pd.isna(v.iloc[-1]) else float("nan")) for k, v in out.items()}
    out["latest"] = latest
    return out


# --------------------------------------------------------------------------- #
# ENSEMBLE FORECASTER
# --------------------------------------------------------------------------- #

def _build_feature_matrix(close: pd.Series, indicators: dict) -> pd.DataFrame:
    """Engineered features: lag returns + key indicators."""
    df = pd.DataFrame(index=close.index)
    df["lag_1"] = close.shift(1)
    df["lag_2"] = close.shift(2)
    df["lag_3"] = close.shift(3)
    df["ret_1"] = close.pct_change(1)
    df["ret_3"] = close.pct_change(3)
    df["ret_7"] = close.pct_change(7)
    df["sma_7"] = indicators["sma_7"]
    df["sma_30"] = indicators["sma_30"]
    df["rsi_14"] = indicators["rsi_14"]
    df["macd"] = indicators["macd"]
    df["macd_signal"] = indicators["macd_signal"]
    return df


def forecast_ensemble(history: pd.DataFrame, indicators: dict | None = None) -> tuple[float, float, float]:
    """
    Returns (prediction, lower_95, upper_95) for the NEXT close price.

    Uses an average of LinearRegression, RandomForestRegressor, and
    GradientBoostingRegressor trained on engineered features. The CI is
    derived from the std of training residuals.

    If history is too short, falls back to a single LinearRegression on the
    raw price series (mirrors original L67-76 behaviour).
    """
    close = history["close"].astype(float)

    if indicators is None:
        indicators = compute_indicators(history)

    features = _build_feature_matrix(close, indicators)
    target = close

    aligned = pd.concat([features, target.rename("y")], axis=1).dropna()
    if len(aligned) < 15:
        return _fallback_linear_forecast(close)

    X = aligned.drop(columns=["y"]).to_numpy()
    y = aligned["y"].to_numpy()

    models = [
        LinearRegression(),
        RandomForestRegressor(n_estimators=100, max_depth=5, random_state=42, n_jobs=1),
        GradientBoostingRegressor(n_estimators=100, max_depth=3, random_state=42),
    ]

    preds_train = np.zeros_like(y, dtype=float)
    next_preds: list[float] = []
    last_row = X[-1].reshape(1, -1)

    for m in models:
        m.fit(X, y)
        preds_train += m.predict(X)
        next_preds.append(float(m.predict(last_row)[0]))

    preds_train /= len(models)
    residuals = y - preds_train
    sigma = float(np.std(residuals))

    prediction = float(np.mean(next_preds))
    lower = prediction - 1.96 * sigma
    upper = prediction + 1.96 * sigma
    return prediction, lower, upper


def _fallback_linear_forecast(close: pd.Series) -> tuple[float, float, float]:
    y = close.to_numpy(dtype=float)
    n = len(y)
    if n < 2:
        # Not enough data — echo the last known price with zero band.
        last = float(y[-1]) if n else 0.0
        return last, last, last
    X = np.arange(n).reshape(-1, 1)
    m = LinearRegression().fit(X, y)
    prediction = float(m.predict(np.array([[n]]))[0])
    residuals = y - m.predict(X)
    sigma = float(np.std(residuals))
    return prediction, prediction - 1.96 * sigma, prediction + 1.96 * sigma


# --------------------------------------------------------------------------- #
# SIGNAL ENGINE — BUY / SELL / HOLD
# --------------------------------------------------------------------------- #

Action = Literal["BUY", "SELL", "HOLD"]


@dataclass
class SignalBreakdown:
    label: str
    vote: int               # -1, 0, +1
    detail: str


@dataclass
class Signal:
    action: Action
    confidence: float       # 0.0 .. 1.0
    score: int
    breakdown: list[SignalBreakdown]


def decide_signal(price: float, indicators: dict, prediction: float) -> Signal:
    """
    Five-signal voting engine. Returns BUY/SELL/HOLD plus per-indicator votes.
    """
    latest = indicators["latest"]
    rsi_v = latest.get("rsi_14", float("nan"))
    macd_v = latest.get("macd", float("nan"))
    macd_sig = latest.get("macd_signal", float("nan"))
    sma_7 = latest.get("sma_7", float("nan"))
    sma_30 = latest.get("sma_30", float("nan"))
    bb_low = latest.get("bb_lower", float("nan"))
    bb_up = latest.get("bb_upper", float("nan"))

    breakdown: list[SignalBreakdown] = []
    score = 0

    # 1. RSI mean reversion
    if not np.isnan(rsi_v):
        if rsi_v < 30:
            score += 1
            breakdown.append(SignalBreakdown("RSI(14)", +1, f"{rsi_v:.1f} - OVERSOLD"))
        elif rsi_v > 70:
            score -= 1
            breakdown.append(SignalBreakdown("RSI(14)", -1, f"{rsi_v:.1f} - OVERBOUGHT"))
        else:
            breakdown.append(SignalBreakdown("RSI(14)", 0, f"{rsi_v:.1f} - NEUTRAL"))
    else:
        breakdown.append(SignalBreakdown("RSI(14)", 0, "N/A"))

    # 2. MACD momentum
    if not (np.isnan(macd_v) or np.isnan(macd_sig)):
        if macd_v > macd_sig:
            score += 1
            breakdown.append(SignalBreakdown("MACD", +1, f"{macd_v:+.2f} > SIG {macd_sig:+.2f}"))
        elif macd_v < macd_sig:
            score -= 1
            breakdown.append(SignalBreakdown("MACD", -1, f"{macd_v:+.2f} < SIG {macd_sig:+.2f}"))
        else:
            breakdown.append(SignalBreakdown("MACD", 0, "FLAT"))
    else:
        breakdown.append(SignalBreakdown("MACD", 0, "N/A"))

    # 3. SMA trend
    if not (np.isnan(sma_7) or np.isnan(sma_30)):
        if sma_7 > sma_30:
            score += 1
            breakdown.append(SignalBreakdown("SMA TREND", +1, f"SMA7 {sma_7:.2f} > SMA30 {sma_30:.2f}"))
        elif sma_7 < sma_30:
            score -= 1
            breakdown.append(SignalBreakdown("SMA TREND", -1, f"SMA7 {sma_7:.2f} < SMA30 {sma_30:.2f}"))
        else:
            breakdown.append(SignalBreakdown("SMA TREND", 0, "FLAT"))
    else:
        breakdown.append(SignalBreakdown("SMA TREND", 0, "N/A"))

    # 4. Bollinger envelope
    if not (np.isnan(bb_low) or np.isnan(bb_up)):
        if price < bb_low:
            score += 1
            breakdown.append(SignalBreakdown("BOLLINGER", +1, f"PX {price:.2f} < LOW {bb_low:.2f}"))
        elif price > bb_up:
            score -= 1
            breakdown.append(SignalBreakdown("BOLLINGER", -1, f"PX {price:.2f} > UP {bb_up:.2f}"))
        else:
            breakdown.append(SignalBreakdown("BOLLINGER", 0, "IN BAND"))
    else:
        breakdown.append(SignalBreakdown("BOLLINGER", 0, "N/A"))

    # 5. Forecast direction
    threshold_up = price * 1.005
    threshold_dn = price * 0.995
    if prediction > threshold_up:
        score += 1
        breakdown.append(SignalBreakdown("FORECAST", +1, f"{prediction:.2f} > {threshold_up:.2f}"))
    elif prediction < threshold_dn:
        score -= 1
        breakdown.append(SignalBreakdown("FORECAST", -1, f"{prediction:.2f} < {threshold_dn:.2f}"))
    else:
        breakdown.append(SignalBreakdown("FORECAST", 0, f"{prediction:.2f} - FLAT"))

    if score >= 2:
        action: Action = "BUY"
    elif score <= -2:
        action = "SELL"
    else:
        action = "HOLD"

    confidence = min(abs(score) / 5.0, 1.0)
    return Signal(action=action, confidence=confidence, score=score, breakdown=breakdown)


# --------------------------------------------------------------------------- #
# BACKTEST
# --------------------------------------------------------------------------- #

def backtest_walkforward(history: pd.DataFrame, lookback: int = 30) -> tuple[int, int]:
    """
    Walk-forward replay: for each of the last `lookback` days, generate the
    signal from the data available up to that day, then compare against the
    realized next-day return.

    A win = (BUY and next-day return > 0) or (SELL and next-day return < 0).
    HOLD outcomes are excluded from the denominator.
    Returns (wins, decisions_taken).
    """
    if len(history) < lookback + 30:
        return 0, 0

    wins = 0
    decisions = 0
    for i in range(len(history) - lookback - 1, len(history) - 1):
        window = history.iloc[: i + 1]
        if len(window) < 30:
            continue
        try:
            inds = compute_indicators(window)
            pred, _, _ = forecast_ensemble(window, inds)
            sig = decide_signal(float(window["close"].iloc[-1]), inds, pred)
        except Exception:
            continue
        if sig.action == "HOLD":
            continue
        decisions += 1
        next_ret = history["close"].iloc[i + 1] - history["close"].iloc[i]
        if (sig.action == "BUY" and next_ret > 0) or (sig.action == "SELL" and next_ret < 0):
            wins += 1
    return wins, decisions


# --------------------------------------------------------------------------- #
# PROCUREMENT PRICING
# --------------------------------------------------------------------------- #

@dataclass
class Pricing:
    metal_value: float
    making_cost: float
    tax_amount: float
    tax_breakdown: str
    total: float


def compute_pricing(
    rate_per_gram: float,
    weight: float,
    purity_factor: float,
    making_type: Literal["Percentage", "Flat Rate"],
    making_value: float,
    market_key: str,
) -> Pricing:
    """
    Generalized procurement math. Replaces L186-198 logic; works for any
    metal/purity, not just 22K gold.
    """
    market = MARKET_DB[market_key]
    sym = market["sym"]
    effective_rate = rate_per_gram * purity_factor
    metal_value = effective_rate * weight

    if making_type == "Percentage":
        making_cost = metal_value * (making_value / 100.0)
    else:
        making_cost = making_value * weight

    if market["tax_type"] == "SPLIT":
        gold_tax = metal_value * market["gold_tax"]
        making_tax = making_cost * market["make_tax"]
        tax_amount = gold_tax + making_tax
        tax_breakdown = (
            f"TAX: Metal ({market['gold_tax']*100:.1f}%) = {sym}{gold_tax:,.2f} | "
            f"Making ({market['make_tax']*100:.1f}%) = {sym}{making_tax:,.2f}"
        )
    else:
        tax_amount = (metal_value + making_cost) * market["tax_rate"]
        tax_breakdown = f"TAX: Flat ({market['tax_rate']*100:.1f}%) = {sym}{tax_amount:,.2f}"

    total = metal_value + making_cost + tax_amount
    return Pricing(metal_value, making_cost, tax_amount, tax_breakdown, total)


# --------------------------------------------------------------------------- #
# PDF REPORT
# --------------------------------------------------------------------------- #

def _ascii_sym(currency: str) -> str:
    """fpdf2 latin-1 fonts cant render Rs/AED/SAR symbols. Map to currency code."""
    return f"{currency} "


def create_pdf_report(
    metal_name: str,
    purity_label: str,
    purity_factor: float,
    market: str,
    currency: str,
    weight: float,
    rate_per_gram: float,
    pricing: Pricing,
    timestamp: str | None = None,
) -> bytes:
    """
    Generalized from L78-112. Works for any metal and any purity.
    Uses ASCII currency codes instead of unicode symbols so the default
    Courier font (latin-1) doesn't choke on Rs/AED/etc.
    """
    if timestamp is None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sym = _ascii_sym(currency)

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Courier", style="B", size=16)
    pdf.cell(0, 10, "SECURE PROCUREMENT QUOTATION", ln=True, align="C")
    pdf.set_font("Courier", size=10)
    pdf.cell(0, 10, f"TIMESTAMP: {timestamp} | REGION: {market}", ln=True, align="C")
    pdf.line(10, 30, 200, 30)
    pdf.ln(10)

    pdf.set_font("Courier", style="B", size=12)
    pdf.cell(0, 10, "COMMODITY SPECIFICATIONS", ln=True)
    pdf.set_font("Courier", size=12)
    pdf.cell(100, 8, f"Metal: {metal_name}")
    pdf.cell(90, 8, f"Weight: {weight} Grams", ln=True)
    pdf.cell(100, 8, f"Purity: {purity_label} ({purity_factor*100:.1f}%)")
    pdf.cell(90, 8, f"Spot Rate (1g): {sym}{rate_per_gram:,.2f}", ln=True)
    pdf.ln(5)

    pdf.set_font("Courier", style="B", size=12)
    pdf.cell(0, 10, "FINANCIAL BREAKDOWN", ln=True)
    pdf.set_font("Courier", size=12)
    pdf.cell(120, 8, "Base Metal Value:")
    pdf.cell(70, 8, f"{sym}{pricing.metal_value:,.2f}", align="R", ln=True)
    pdf.cell(120, 8, "Workmanship:")
    pdf.cell(70, 8, f"{sym}{pricing.making_cost:,.2f}", align="R", ln=True)
    pdf.cell(120, 8, "Taxes & Levies:")
    pdf.cell(70, 8, f"{sym}{pricing.tax_amount:,.2f}", align="R", ln=True)
    pdf.line(10, pdf.get_y() + 2, 200, pdf.get_y() + 2)
    pdf.ln(5)

    pdf.set_font("Courier", style="B", size=14)
    pdf.cell(120, 10, "NET PAYABLE:")
    pdf.cell(70, 10, f"{sym}{pricing.total:,.2f}", align="R", ln=True)
    return bytes(pdf.output())
