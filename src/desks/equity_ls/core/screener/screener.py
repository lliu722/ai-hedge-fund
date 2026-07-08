"""
A2 Screener — 6-step screening methodology for the Equity L/S desk.

Step 1: Hard Eligibility Filters
Step 2: Peer Group Setup
Step 3: Screening Engines (Momentum / Quality / Growth / Valuation /
         Balance Sheet / Liquidity / Catalyst / Theme-Sector / Risk)
Step 4: Composite Score (100 pts max; risk penalty up to -20)
Step 5: Candidate Classification
Step 6: Research Handoff routing signal

Returns a ScreeningResult — fed directly into A2 deep_dive.py as the
screening context block.
"""
from __future__ import annotations

import functools
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import yfinance as yf


# ── Sector ETF map ────────────────────────────────────────────────────────────
# Used for relative-strength and sector-momentum checks.

SECTOR_ETF: dict[str, str] = {
    "Technology":              "XLK",
    "Communication Services":  "XLC",
    "Consumer Cyclical":       "XLY",
    "Consumer Defensive":      "XLP",
    "Energy":                  "XLE",
    "Financials":              "XLF",
    "Healthcare":              "XLV",
    "Industrials":             "XLI",
    "Basic Materials":         "XLB",
    "Real Estate":             "XLRE",
    "Utilities":               "XLU",
}

THEME_ETF: dict[str, str] = {
    "AI infrastructure":      "BOTZ",
    "Semiconductors":         "SOXX",
    "Cloud":                  "SKYY",
    "Fintech":                "ARKF",
    "Defence":                "ITA",
    "Data center power":      "GRID",
    "Commodities":            "DJP",
    "Crypto-equity":          "BITQ",
    "Biotech":                "XBI",
    "Payments":               "IPAY",
}

MARKET_ETF = "SPY"
NASDAQ_ETF = "QQQ"


# ── Output types ──────────────────────────────────────────────────────────────

@dataclass
class ComponentScore:
    raw: float       # actual score earned
    max: float       # maximum possible
    notes: list[str] = field(default_factory=list)

    @property
    def pct(self) -> float:
        return round(self.raw / self.max, 3) if self.max else 0.0


@dataclass
class ScreeningResult:
    ticker: str
    run_date: str

    # Step 1
    hard_pass: bool = True
    hard_fail_reason: str = ""

    # Step 2
    sector: str = ""
    industry: str = ""
    theme: str = ""
    sector_etf: str = ""
    theme_etf: str = ""

    # Step 3 component scores
    momentum:      ComponentScore = field(default_factory=lambda: ComponentScore(0, 25))
    quality:       ComponentScore = field(default_factory=lambda: ComponentScore(0, 20))
    growth:        ComponentScore = field(default_factory=lambda: ComponentScore(0, 15))
    valuation:     ComponentScore = field(default_factory=lambda: ComponentScore(0, 15))
    balance_sheet: ComponentScore = field(default_factory=lambda: ComponentScore(0, 10))
    liquidity:     ComponentScore = field(default_factory=lambda: ComponentScore(0, 5))
    catalyst:      ComponentScore = field(default_factory=lambda: ComponentScore(0, 15))
    risk_penalty:  ComponentScore = field(default_factory=lambda: ComponentScore(0, 20))  # subtracted

    # Step 4
    composite_score: float = 0.0

    # Step 5
    classification: str = ""     # e.g. "Deep-Dive / High-Priority Long"
    score_band: str = ""         # e.g. "80–100"

    # Step 6
    handoff_trigger: str = ""    # e.g. "Deep Dive Trigger"
    handoff_rationale: str = ""

    # All flags raised during screening
    flags: list[str] = field(default_factory=list)

    # Raw data cache (for prompt formatting)
    raw: dict = field(default_factory=dict)


# ── Price history helper ──────────────────────────────────────────────────────

def _price_returns(ticker: str) -> dict:
    """Fetch 2y of daily closes and compute returns at multiple horizons.
    (2y, not 1y — the 252-day return needs 253 rows and a 1y fetch only has ~250,
    which silently disabled the 12-1 momentum signal.)"""
    try:
        hist = yf.Ticker(ticker).history(period="2y")
        if hist.empty:
            return {}
        closes = hist["Close"].dropna()
        if len(closes) < 2:
            return {}

        def ret(n_days: int) -> Optional[float]:
            if len(closes) >= n_days + 1:
                return round((closes.iloc[-1] / closes.iloc[-n_days - 1] - 1) * 100, 2)
            return None

        ma50  = round(closes.tail(50).mean(), 4)  if len(closes) >= 50  else None
        ma200 = round(closes.tail(200).mean(), 4) if len(closes) >= 200 else None
        high52 = float(closes.tail(252).max())  # 52-week high, not full-fetch high
        price  = float(closes.iloc[-1])

        return {
            "return_1d":   ret(1),
            "return_5d":   ret(5),
            "return_1m":   ret(21),
            "return_3m":   ret(63),
            "return_6m":   ret(126),
            "return_12m":  ret(252),
            "ma50":        ma50,
            "ma200":       ma200,
            "price_vs_ma50":  round((price / ma50 - 1) * 100, 2)  if ma50  else None,
            "price_vs_ma200": round((price / ma200 - 1) * 100, 2) if ma200 else None,
            "drawdown_52w":   round((price / high52 - 1) * 100, 2),
            "price":          price,
        }
    except Exception:
        return {}


@functools.lru_cache(maxsize=64)
def _etf_return(etf: str, n_days: int = 63) -> Optional[float]:
    """n-day return for an ETF. Cached per process — a monitor run over 100+
    names would otherwise refetch SPY and each sector ETF once per ticker."""
    try:
        hist = yf.Ticker(etf).history(period="6mo")["Close"].dropna()
        if len(hist) >= n_days + 1:
            return round((hist.iloc[-1] / hist.iloc[-n_days - 1] - 1) * 100, 2)
    except Exception:
        pass
    return None


def _relative_strength(ticker_ret: Optional[float], bench_ret: Optional[float]) -> Optional[float]:
    """Excess return of ticker vs benchmark over same period."""
    if ticker_ret is None or bench_ret is None:
        return None
    return round(ticker_ret - bench_ret, 2)


# ── Step 1: Hard eligibility filters ─────────────────────────────────────────

def _step1_hard_filters(ticker: str, md: dict) -> tuple[bool, str]:
    """Returns (pass, fail_reason). Fail = stop immediately."""
    # Market cap floor: $300M minimum
    cap = md.get("market_cap") or 0
    if cap < 300_000_000:
        return False, f"Market cap too small: ${cap/1e6:.0f}M (min $300M)"

    # Liquidity floor: avg 10d volume > 200k
    vol = md.get("avg_volume_10d") or 0
    if vol < 200_000:
        return False, f"Avg volume too low: {vol:,.0f} (min 200k)"

    # Price floor: $1 minimum (avoid penny stocks / extreme speculation)
    price = md.get("price") or 0
    if price < 1.0:
        return False, f"Price below $1: ${price:.3f}"

    # Data quality: must have revenue or market cap
    rev = md.get("revenue") or 0
    if cap == 0 and rev == 0:
        return False, "No financial data available — data quality fail"

    return True, ""


# ── Step 2: Peer group setup ──────────────────────────────────────────────────

def _step2_peer_group(md: dict) -> tuple[str, str, str, str, str]:
    """Returns (sector, industry, theme, sector_etf, theme_etf)."""
    sector   = md.get("sector", "") or ""
    industry = md.get("industry", "") or ""

    # Best-effort theme assignment from industry/sector keywords
    industry_lower = industry.lower()
    theme = ""
    if any(k in industry_lower for k in ["semiconductor", "chip"]):
        theme = "Semiconductors"
    elif any(k in industry_lower for k in ["software", "saas", "cloud"]):
        theme = "Cloud"
    elif any(k in industry_lower for k in ["payment", "fintech"]):
        theme = "Fintech"
    elif any(k in industry_lower for k in ["biotech", "biopharmaceutical"]):
        theme = "Biotech"
    elif any(k in industry_lower for k in ["defense", "aerospace"]):
        theme = "Defence"
    elif "ai" in industry_lower or "artificial intelligence" in industry_lower:
        theme = "AI infrastructure"
    elif any(k in industry_lower for k in ["bitcoin", "crypto", "blockchain"]):
        theme = "Crypto-equity"

    sector_etf = SECTOR_ETF.get(sector, "SPY")
    theme_etf  = THEME_ETF.get(theme, "")
    return sector, industry, theme, sector_etf, theme_etf


# ── Step 3a: Momentum screen (max 25 pts) ────────────────────────────────────

def _score_momentum(pr: dict, sector_etf: str) -> ComponentScore:
    score = 0.0
    notes = []

    r1m  = pr.get("return_1m")
    r3m  = pr.get("return_3m")
    r6m  = pr.get("return_6m")
    r12m = pr.get("return_12m")

    # 12-1 month momentum (primary signal, 8 pts)
    if r12m is not None and r1m is not None:
        mom_12_1 = r12m - r1m
        if mom_12_1 > 20:
            score += 8; notes.append(f"Strong 12-1m momentum: {mom_12_1:.1f}%")
        elif mom_12_1 > 5:
            score += 5; notes.append(f"Positive 12-1m momentum: {mom_12_1:.1f}%")
        elif mom_12_1 < -20:
            notes.append(f"Negative 12-1m momentum: {mom_12_1:.1f}%")
        else:
            score += 2

    # 3m return (4 pts)
    if r3m is not None:
        if r3m > 15:
            score += 4; notes.append(f"Strong 3M return: +{r3m:.1f}%")
        elif r3m > 5:
            score += 2.5
        elif r3m > 0:
            score += 1

    # Price vs 50d / 200d MA (5 pts)
    vs50  = pr.get("price_vs_ma50")
    vs200 = pr.get("price_vs_ma200")
    if vs50 is not None and vs50 > 0:
        score += 2; notes.append(f"Above 50d MA: +{vs50:.1f}%")
    if vs200 is not None and vs200 > 0:
        score += 3; notes.append(f"Above 200d MA: +{vs200:.1f}%")

    # Relative strength vs sector ETF (5 pts) — 3M window
    rs_sector = None
    if sector_etf:
        etf_3m = _etf_return(sector_etf, 63)
        rs_sector = _relative_strength(r3m, etf_3m)
        if rs_sector is not None:
            if rs_sector > 10:
                score += 5; notes.append(f"Strong RS vs {sector_etf}: +{rs_sector:.1f}%")
            elif rs_sector > 3:
                score += 3
            elif rs_sector > 0:
                score += 1

    # Relative strength vs SPY (3 pts)
    spy_3m = _etf_return(MARKET_ETF, 63)
    rs_spy = _relative_strength(r3m, spy_3m)
    if rs_spy is not None:
        if rs_spy > 5:
            score += 3; notes.append(f"Outperforming SPY 3M: +{rs_spy:.1f}%")
        elif rs_spy > 0:
            score += 1.5

    # Drawdown from 52w high (bonus/flag)
    dd = pr.get("drawdown_52w")
    if dd is not None and dd < -40:
        notes.append(f"Large drawdown from 52w high: {dd:.1f}%")

    return ComponentScore(min(score, 25), 25, notes)


# ── Step 3b: Quality screen (max 20 pts) ────────────────────────────────────

def _score_quality(md: dict) -> ComponentScore:
    score = 0.0
    notes = []

    # Gross margin (4 pts)
    gm = md.get("gross_margins")
    if gm is not None:
        if gm > 0.6:
            score += 4; notes.append(f"High gross margin: {gm:.0%}")
        elif gm > 0.4:
            score += 2.5
        elif gm > 0.2:
            score += 1
        else:
            notes.append(f"Low gross margin: {gm:.0%}")

    # Operating margin (3 pts)
    om = md.get("operating_margins")
    if om is not None:
        if om > 0.2:
            score += 3; notes.append(f"Strong operating margin: {om:.0%}")
        elif om > 0.1:
            score += 2
        elif om > 0:
            score += 1
        else:
            notes.append(f"Negative operating margin: {om:.0%}")

    # FCF generation (4 pts)
    fcf = md.get("free_cash_flow") or 0
    cap = md.get("market_cap") or 1
    fcf_yield = fcf / cap if cap else 0
    if fcf > 0:
        score += 2
        if fcf_yield > 0.04:
            score += 2; notes.append(f"Strong FCF yield: {fcf_yield:.1%}")
        elif fcf_yield > 0.02:
            score += 1
    else:
        notes.append("Negative FCF")

    # ROE (3 pts)
    roe = md.get("return_on_equity")
    if roe is not None:
        if roe > 0.25:
            score += 3; notes.append(f"High ROE: {roe:.0%}")
        elif roe > 0.15:
            score += 2
        elif roe > 0.05:
            score += 1
        else:
            notes.append(f"Weak ROE: {roe:.0%}")

    # Earnings growth consistency (proxy: earnings_growth from B2) (3 pts)
    eg = md.get("earnings_growth")
    if eg is not None:
        if eg > 0.2:
            score += 3; notes.append(f"Strong earnings growth: {eg:.0%}")
        elif eg > 0.05:
            score += 2
        elif eg > 0:
            score += 1
        else:
            notes.append(f"Declining earnings: {eg:.0%}")

    # Net margin (3 pts)
    nm = md.get("profit_margins")
    if nm is not None:
        if nm > 0.2:
            score += 3; notes.append(f"High net margin: {nm:.0%}")
        elif nm > 0.1:
            score += 2
        elif nm > 0:
            score += 1

    return ComponentScore(min(score, 20), 20, notes)


# ── Step 3c: Growth screen (max 15 pts) ──────────────────────────────────────

def _score_growth(md: dict) -> ComponentScore:
    score = 0.0
    notes = []

    # Revenue growth (5 pts)
    rg = md.get("revenue_growth")
    if rg is not None:
        if rg > 0.3:
            score += 5; notes.append(f"High revenue growth: {rg:.0%}")
        elif rg > 0.15:
            score += 3.5
        elif rg > 0.05:
            score += 2
        elif rg > 0:
            score += 1
        else:
            notes.append(f"Revenue declining: {rg:.0%}")

    # EPS growth (proxy: earnings_growth) (4 pts)
    eg = md.get("earnings_growth")
    if eg is not None:
        if eg > 0.25:
            score += 4; notes.append(f"Strong EPS growth: {eg:.0%}")
        elif eg > 0.1:
            score += 2.5
        elif eg > 0:
            score += 1

    # FCF growth (proxy: positive FCF + positive revenue growth) (3 pts)
    fcf = md.get("free_cash_flow") or 0
    if fcf > 0 and rg is not None and rg > 0.1:
        score += 3; notes.append("FCF positive + revenue growing")
    elif fcf > 0:
        score += 1.5

    # Forward growth: fwd P/E lower than TTM P/E implies growth expected (3 pts)
    pe_ttm = md.get("trailing_pe")
    pe_fwd = md.get("forward_pe")
    if pe_ttm and pe_fwd and pe_ttm > 0 and pe_fwd > 0:
        implied_growth = pe_ttm / pe_fwd - 1
        if implied_growth > 0.15:
            score += 3; notes.append(f"Forward estimates imply ~{implied_growth:.0%} EPS growth")
        elif implied_growth > 0.05:
            score += 1.5

    return ComponentScore(min(score, 15), 15, notes)


# ── Step 3d: Valuation screen (max 15 pts) ───────────────────────────────────

def _score_valuation(md: dict) -> ComponentScore:
    """Higher score = more attractive valuation. Expensive names score low."""
    score = 0.0
    notes = []

    # FCF yield (5 pts) — most reliable valuation metric
    fcf = md.get("free_cash_flow") or 0
    cap = md.get("market_cap") or 1
    fcf_yield = fcf / cap if cap and fcf > 0 else 0
    if fcf_yield > 0.06:
        score += 5; notes.append(f"Attractive FCF yield: {fcf_yield:.1%}")
    elif fcf_yield > 0.03:
        score += 3
    elif fcf_yield > 0.01:
        score += 1.5
    elif fcf <= 0:
        notes.append("Negative FCF — no FCF yield")

    # EV/EBITDA (4 pts)
    ev_ebitda = md.get("ev_to_ebitda")
    if ev_ebitda is not None and ev_ebitda > 0:
        if ev_ebitda < 10:
            score += 4; notes.append(f"Cheap EV/EBITDA: {ev_ebitda:.1f}x")
        elif ev_ebitda < 18:
            score += 2.5
        elif ev_ebitda < 30:
            score += 1
        else:
            notes.append(f"Expensive EV/EBITDA: {ev_ebitda:.1f}x")

    # Forward P/E (3 pts)
    fpe = md.get("forward_pe")
    if fpe is not None and fpe > 0:
        if fpe < 15:
            score += 3; notes.append(f"Cheap fwd P/E: {fpe:.1f}x")
        elif fpe < 25:
            score += 2
        elif fpe < 40:
            score += 1
        else:
            notes.append(f"Expensive fwd P/E: {fpe:.1f}x")

    # P/S (3 pts — for high-growth names without earnings)
    ps = md.get("price_to_sales")
    if ps is not None and ps > 0:
        if ps < 2:
            score += 3; notes.append(f"Cheap P/S: {ps:.1f}x")
        elif ps < 5:
            score += 2
        elif ps < 10:
            score += 1
        else:
            notes.append(f"Expensive P/S: {ps:.1f}x")

    # Analyst target upside (bonus signal, not scored — just flagged)
    price = md.get("price")
    target = md.get("target_mean_price")
    if price and target and price > 0:
        upside = (target / price - 1) * 100
        if upside > 20:
            notes.append(f"Analyst consensus: {upside:.0f}% upside to target ${target:.0f}")
        elif upside < -10:
            notes.append(f"Analyst consensus below market: {upside:.0f}% to target ${target:.0f}")

    return ComponentScore(min(score, 15), 15, notes)


# ── Step 3e: Balance sheet screen (max 7 pts) ────────────────────────────────

def _score_balance_sheet(md: dict) -> ComponentScore:
    score = 0.0
    notes = []

    # D/E ratio (3 pts)
    de = md.get("debt_to_equity")
    if de is not None:
        if de < 0.3:
            score += 3; notes.append(f"Low leverage: D/E {de:.2f}")
        elif de < 1.0:
            score += 2
        elif de < 2.0:
            score += 1
        else:
            notes.append(f"High leverage: D/E {de:.2f}")

    # Current ratio (2 pts)
    cr = md.get("current_ratio")
    if cr is not None:
        if cr > 2.0:
            score += 2; notes.append(f"Strong liquidity: current ratio {cr:.2f}")
        elif cr > 1.2:
            score += 1.5
        elif cr > 0.8:
            score += 0.5
        else:
            notes.append(f"Tight liquidity: current ratio {cr:.2f}")

    # FCF positive = no refinancing pressure (2 pts)
    fcf = md.get("free_cash_flow") or 0
    if fcf > 0:
        score += 2

    return ComponentScore(min(score, 10), 10, notes)


# ── Step 3f: Liquidity screen (max 5 pts) ────────────────────────────────────

def _score_liquidity(md: dict) -> ComponentScore:
    score = 0.0
    notes = []

    cap = md.get("market_cap") or 0
    vol = md.get("avg_volume_10d") or 0
    price = md.get("price") or 1

    # Market cap (2 pts)
    if cap > 10_000_000_000:
        score += 2; notes.append(f"Large cap: ${cap/1e9:.0f}B")
    elif cap > 2_000_000_000:
        score += 1.5
    elif cap > 500_000_000:
        score += 1

    # Avg daily dollar volume (3 pts)
    adv_usd = vol * price
    if adv_usd > 100_000_000:
        score += 3; notes.append(f"High ADV: ${adv_usd/1e6:.0f}M")
    elif adv_usd > 20_000_000:
        score += 2
    elif adv_usd > 5_000_000:
        score += 1
    else:
        notes.append(f"Low ADV: ${adv_usd/1e6:.1f}M — liquidity risk")

    return ComponentScore(min(score, 5), 5, notes)


# ── Step 3g: Catalyst screen (max 15 pts) ────────────────────────────────────

def _score_catalyst(md: dict, days_to_earnings: Optional[int]) -> ComponentScore:
    score = 0.0
    notes = []

    # Analyst recommendation (5 pts)
    rec = (md.get("recommendation") or "").lower()
    n_analysts = md.get("analyst_count") or 0
    if "strong_buy" in rec or "strongbuy" in rec:
        score += 5; notes.append(f"Strong Buy consensus (n={n_analysts})")
    elif "buy" in rec:
        score += 4; notes.append(f"Buy consensus (n={n_analysts})")
    elif "hold" in rec:
        score += 2
    elif "sell" in rec or "underperform" in rec:
        notes.append(f"Sell/Underperform consensus (n={n_analysts})")

    # Price target upside as catalyst signal (5 pts)
    price = md.get("price") or 0
    target = md.get("target_mean_price") or 0
    if price > 0 and target > 0:
        upside = (target / price - 1)
        if upside > 0.3:
            score += 5; notes.append(f"High analyst upside: {upside:.0%}")
        elif upside > 0.15:
            score += 3
        elif upside > 0.05:
            score += 1

    # Earnings proximity — within 30 days is a catalyst (positive or binary risk)
    if days_to_earnings is not None:
        if 3 <= days_to_earnings <= 30:
            score += 3; notes.append(f"Earnings in {days_to_earnings} days — catalyst window")
        elif days_to_earnings < 3:
            notes.append(f"Earnings imminent ({days_to_earnings}d) — binary event")

    # Short squeeze potential (high short = contrarian catalyst) (2 pts)
    short_float = md.get("short_percent_float") or 0
    if short_float > 0.15:
        score += 2; notes.append(f"High short interest: {short_float:.0%} — squeeze potential")
    elif short_float > 0.08:
        score += 1

    return ComponentScore(min(score, 15), 15, notes)


# ── Step 3h: Risk penalty (subtract up to 20 pts) ────────────────────────────

def _score_risk(md: dict, pr: dict, flags: list[str]) -> tuple[ComponentScore, list[str]]:
    """Returns (risk_component, updated_flags). Penalty is subtracted from total."""
    penalty = 0.0
    risk_notes = []

    # Large drawdown
    dd = pr.get("drawdown_52w")
    if dd is not None and dd < -35:
        penalty += 4; risk_notes.append(f"Large drawdown: {dd:.1f}% from 52w high")
        flags.append(f"Large drawdown from 52w high: {dd:.1f}%")

    # High volatility (beta proxy)
    beta = md.get("beta")
    if beta is not None and abs(beta) > 2.5:
        penalty += 3; risk_notes.append(f"High volatility: beta {beta:.2f}")
        flags.append(f"High beta: {beta:.2f}")

    # Valuation extreme (fwd P/E > 60 without growth > 30%)
    fpe = md.get("forward_pe")
    rg = md.get("revenue_growth") or 0
    if fpe is not None and fpe > 60 and rg < 0.30:
        penalty += 4; risk_notes.append(f"Valuation extreme: fwd P/E {fpe:.0f}x without commensurate growth")
        flags.append(f"Valuation extreme: fwd P/E {fpe:.0f}x")

    # Weak balance sheet
    de = md.get("debt_to_equity")
    cr = md.get("current_ratio")
    if de is not None and de > 3.0:
        penalty += 3; risk_notes.append(f"Weak balance sheet: D/E {de:.1f}")
    if cr is not None and cr < 0.8:
        penalty += 2; risk_notes.append(f"Liquidity risk: current ratio {cr:.2f}")

    # Negative FCF + high burn
    fcf = md.get("free_cash_flow") or 0
    cap = md.get("market_cap") or 1
    if fcf < 0 and abs(fcf) / cap > 0.10:
        penalty += 3; risk_notes.append(f"High burn rate: FCF burn is {abs(fcf)/cap:.0%} of market cap")
        flags.append("High FCF burn rate")

    # Negative momentum (broken trend)
    r3m = pr.get("return_3m")
    r6m = pr.get("return_6m")
    if r3m is not None and r6m is not None and r3m < -15 and r6m < -25:
        penalty += 3; risk_notes.append(f"Broken trend: -3M={r3m:.1f}%, -6M={r6m:.1f}%")
        flags.append("Broken technical trend (3M and 6M negative)")

    return ComponentScore(min(penalty, 20), 20, risk_notes), flags


# ── Step 4: Composite score ───────────────────────────────────────────────────

def _composite(s: ScreeningResult) -> float:
    total = (
        s.momentum.raw
        + s.quality.raw
        + s.growth.raw
        + s.valuation.raw
        + s.balance_sheet.raw
        + s.liquidity.raw
        + s.catalyst.raw
        - s.risk_penalty.raw
    )
    return round(max(0.0, total), 1)


# ── Step 5: Classification ────────────────────────────────────────────────────

def _classify(score: float) -> tuple[str, str]:
    if score >= 80:
        return "Deep-Dive / High-Priority Long Candidate", "80–100"
    elif score >= 65:
        return "Watchlist / Monitor Candidate", "65–79"
    elif score >= 50:
        return "Neutral / No Action", "50–64"
    elif score >= 35:
        return "Weak / Avoid Candidate", "35–49"
    else:
        return "Remove / Restrict Review", "<35"


# ── Step 6: Research handoff ──────────────────────────────────────────────────

def _handoff(score: float, days_to_earnings: Optional[int], tier: int) -> tuple[str, str]:
    """
    Routes to a research-job type. "Deep Dive Trigger" is delegated to
    cadence.should_trigger_deep_dive — the single authority on whether a name
    escalates — so this can never disagree with what the monitor actually
    does (2026-07 audit fix; previously this function independently declared
    "T0/T1 always deep-dive" while cadence said "T0 only on a major event").
    """
    from src.desks.equity_ls.core.screener.cadence import is_major_event, should_trigger_deep_dive

    has_major_event = is_major_event(days_to_earnings)

    if should_trigger_deep_dive(tier, score, has_major_event):
        return (
            "Deep Dive Trigger",
            f"Tier {tier} cadence rule fired (score={score:.0f}, major_event={has_major_event}) "
            "— run full TradingAgents deep dive",
        )
    elif days_to_earnings is not None and 0 < days_to_earnings <= 14:
        return "Earnings Preview Trigger", f"Earnings in {days_to_earnings} days — run earnings-focused research"
    elif 65 <= score < 80:
        return "Valuation Report Trigger", "Strong business but conviction depends on valuation — run valuation report"
    elif score < 35:
        return "Avoid Note Trigger", "Poor quality/momentum/risk — write avoid note"
    else:
        return "Monitor", "No immediate action — keep on radar"


# ── Main entry point ──────────────────────────────────────────────────────────

def run(ticker: str, tier: int = 4) -> ScreeningResult:
    """
    Run the full 6-step screening on a ticker.

    Args:
        ticker: Ticker symbol (uppercase).
        tier:   Universe tier from B1 (0=holding, 1=watchlist, 2=sector leader, 4=new)

    Returns:
        ScreeningResult with composite score, classification, and handoff routing.
    """
    from src.desks.equity_ls.infrastructure.b2_data_source.data_sources import (
        get_market_data,
        get_earnings_dates,
    )

    ticker = ticker.upper()
    run_date = datetime.now().strftime("%Y-%m-%d")
    result = ScreeningResult(ticker=ticker, run_date=run_date)

    # Fetch data
    md = get_market_data(ticker)
    if "_error" in md:
        result.hard_pass = False
        result.hard_fail_reason = f"Data fetch failed: {md['_error']}"
        return result

    # Keep raw lean: drop private keys (_quarterly_* hold whole DataFrames)
    result.raw = {k: v for k, v in md.items() if not k.startswith("_")}

    # Earnings proximity
    days_to_earnings: Optional[int] = None
    try:
        earn = get_earnings_dates(ticker)
        ned = earn.get("earnings_date")
        if ned:
            days_to_earnings = (datetime.strptime(str(ned)[:10], "%Y-%m-%d") - datetime.now()).days
            result.raw["next_earnings"] = str(ned)
            result.raw["days_to_earnings"] = days_to_earnings
    except Exception:
        pass

    # Step 1
    hard_pass, fail_reason = _step1_hard_filters(ticker, md)
    result.hard_pass = hard_pass
    result.hard_fail_reason = fail_reason
    if not hard_pass:
        result.classification = "Removed — failed hard filter"
        result.handoff_trigger = "Avoid Note Trigger"
        result.flags.append(f"Hard filter fail: {fail_reason}")
        return result

    # Step 2
    result.sector, result.industry, result.theme, result.sector_etf, result.theme_etf = _step2_peer_group(md)

    # Price history (for momentum)
    pr = _price_returns(ticker)
    result.raw.update(pr)

    # Step 3
    result.momentum      = _score_momentum(pr, result.sector_etf)
    result.quality       = _score_quality(md)
    result.growth        = _score_growth(md)
    result.valuation     = _score_valuation(md)
    result.balance_sheet = _score_balance_sheet(md)
    result.liquidity     = _score_liquidity(md)
    result.catalyst      = _score_catalyst(md, days_to_earnings)
    result.risk_penalty, result.flags = _score_risk(md, pr, result.flags)

    # Step 4
    result.composite_score = _composite(result)

    # Step 5
    result.classification, result.score_band = _classify(result.composite_score)

    # Step 6
    result.handoff_trigger, result.handoff_rationale = _handoff(
        result.composite_score, days_to_earnings, tier
    )

    return result


# ── Prompt formatter (for A2 deep_dive.py) ───────────────────────────────────

def format_for_prompt(sr: ScreeningResult) -> str:
    """Format a ScreeningResult into a readable block for LLM prompts."""

    def _fmt_component(name: str, c: ComponentScore) -> str:
        note_str = (" | " + "; ".join(c.notes)) if c.notes else ""
        return f"  {name:<22} {c.raw:>5.1f} / {c.max:.0f}{note_str}"

    lines = [
        f"SCREENING RESULT — {sr.ticker}",
        f"Run: {sr.run_date} | Sector: {sr.sector} | Industry: {sr.industry}",
        f"Theme: {sr.theme or 'N/A'} | Sector ETF: {sr.sector_etf} | Theme ETF: {sr.theme_etf or 'N/A'}",
        "",
        "COMPONENT SCORES:",
        _fmt_component("Momentum (25)",      sr.momentum),
        _fmt_component("Quality (20)",       sr.quality),
        _fmt_component("Growth (15)",        sr.growth),
        _fmt_component("Valuation (15)",     sr.valuation),
        _fmt_component("Balance Sheet (10)", sr.balance_sheet),
        _fmt_component("Liquidity (5)",      sr.liquidity),
        _fmt_component("Catalyst (15)",      sr.catalyst),
        _fmt_component("Risk Penalty (-20)", sr.risk_penalty),
        "",
        f"COMPOSITE SCORE: {sr.composite_score} / 100",
        f"CLASSIFICATION:  {sr.classification} [{sr.score_band}]",
        f"HANDOFF:         {sr.handoff_trigger} — {sr.handoff_rationale}",
    ]

    if sr.flags:
        lines += ["", "FLAGS:"] + [f"  ⚠️  {f}" for f in sr.flags]

    # Key raw metrics
    r = sr.raw
    lines += [
        "",
        "KEY METRICS:",
        f"  Price: ${r.get('price', 'N/A')} | MktCap: ${(r.get('market_cap') or 0)/1e9:.2f}B | Beta: {r.get('beta', 'N/A')}",
        f"  Returns: 1M={r.get('return_1m', 'N/A')}% 3M={r.get('return_3m', 'N/A')}% 6M={r.get('return_6m', 'N/A')}% 12M={r.get('return_12m', 'N/A')}%",
        f"  vs 50dMA: {r.get('price_vs_ma50', 'N/A')}% | vs 200dMA: {r.get('price_vs_ma200', 'N/A')}% | Drawdown 52w: {r.get('drawdown_52w', 'N/A')}%",
        f"  P/E: {r.get('trailing_pe', 'N/A')} | Fwd P/E: {r.get('forward_pe', 'N/A')} | EV/EBITDA: {r.get('ev_to_ebitda', 'N/A')} | P/S: {r.get('price_to_sales', 'N/A')}",
        f"  Rev Growth: {r.get('revenue_growth', 'N/A')} | Gross Margin: {r.get('gross_margins', 'N/A')} | FCF: ${(r.get('free_cash_flow') or 0)/1e6:.0f}M",
        f"  D/E: {r.get('debt_to_equity', 'N/A')} | Current Ratio: {r.get('current_ratio', 'N/A')} | Short Float: {r.get('short_percent_float', 'N/A')}",
        f"  Next Earnings: {r.get('next_earnings', 'N/A')} ({r.get('days_to_earnings', '?')}d)",
    ]

    return "\n".join(lines)
