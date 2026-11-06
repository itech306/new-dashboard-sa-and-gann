"""Gann screeners: Price-to-Time + 3-6-9 Time Cluster  ->  gann_data.json (read by gann.html).

Pine script "price and time by sourav karhana" ke Module 1 aur Module 2 ka Python port.
Anchors Pine ke ta.pivothigh / ta.pivotlow se aate hain (swing strength = bars each side: 20 / 30 / 40).

Kaise kaam karta hai
  1. Universe: weekly aur monthly window ke top 5 Industry + top 5 Subgroup (screeners 20% in 5 days,
     13% in 5 days, 13% in a Week ke hits se). In groups ke saare stocks, liquidity filter ke saath:
         SMA(close * volume, 20) > 3 crore   aur   close > 20
  2. Har stock ka latest confirmed swing high (MH) aur swing low (ML) anchor banta hai (har strength ke liye).
  3. Sirf AAJ (latest bar) dekha jaata hai:
       Price-to-Time : aaj ka bar == anchor bar + round(base * i), i = 1..9
                       base = anchorPrice / 10^max(0, floor(log10(anchorPrice)) - 1)
       369 Cluster   : aaj ka bar == anchor bar + cycle (30,60,90,...,720). Dono anchors (H aur L) ki lines
                       jab ek hi din milti hain to cluster. Bars mode (trading days) aur Calendar-days mode dono.

Pivot rule (Pine jaisa): center bar left ke L bars se strictly bada (high) / chhota (low) aur right ke L bars se
bada-barabar. Barabar highs me pehla wala pivot hota hai. Pivot tabhi confirm hota hai jab uske baad L bars aa jayein.
"""
import datetime as dt
import json
import math

import numpy as np
import pandas as pd

from screeners import MIN_PRICE, load_sectors

STRENGTHS = (20, 30, 40)
CYCLES = (30, 60, 90, 120, 144, 180, 216, 240, 270, 288, 360, 432, 480, 540, 720)
GROUP_SCREENERS = ("w5_20", "w5_13", "wk13")   # top 5 groups inhi screeners ke hits se bante hain
TOP_N = 5
LIQ_MIN = 3e7                                  # SMA(close * volume, 20) > 3 crore
ONLY_SCREENER_HITS = False                     # True: top groups ke sirf wahi stocks jinhone screener hit diya


def pine_round(x):
    return int(math.floor(x + 0.5))


def last_pivot(a, length, high=True):
    """Index of the latest confirmed pivot high/low in array `a` (None if there is none)."""
    if len(a) < 2 * length + 1:
        return None
    s = pd.Series(a)
    if high:
        left = s.shift(1).rolling(length).max()
        right = s[::-1].shift(1).rolling(length).max()[::-1]
        ok = (s > left) & (s >= right)
    else:
        left = s.shift(1).rolling(length).min()
        right = s[::-1].shift(1).rolling(length).min()[::-1]
        ok = (s < left) & (s <= right)
    idx = np.flatnonzero(ok.values)
    return int(idx[-1]) if len(idx) else None


def price_to_time_bars(price):
    """[(i, bars_to_add)] for x1..x9 (Pine drawGannLines)."""
    if not price or price <= 0:
        return []
    pw = max(0, math.floor(math.log10(price)) - 1)
    base = price / math.pow(10, pw)
    return [(i, pine_round(base * i)) for i in range(1, 10)]


def win_start(asof, p):
    d = dt.date.fromisoformat(asof)
    if p == "w":
        return (d - dt.timedelta(days=6)).isoformat()
    y, m = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
    last = (dt.date(d.year, d.month, 1) - dt.timedelta(days=1)).day   # days in previous month
    return dt.date(y, m, min(d.day, last)).isoformat()


def top_groups(hits, sectors, st, asof):
    syms = {h[2] for h in hits if h[1] in GROUP_SCREENERS and st <= h[0] <= asof}
    ci, cs = {}, {}
    for s in syms:
        ind, sub = (list(sectors.get(s.upper(), ["", ""])) + ["", ""])[:2]
        if ind:
            ci[ind] = ci.get(ind, 0) + 1
        if sub:
            cs[sub] = cs.get(sub, 0) + 1
    rank = lambda c: sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_N]
    return rank(ci), rank(cs), syms


def analyse(h, l, dates, strength):
    """Anchors + today's Gann hits for one stock and one strength. h, l: adjusted high/low arrays."""
    n = len(h)
    today = n - 1
    out = {"a": {}, "pt": [], "cb": [], "cd": []}
    today_date = dt.date.fromisoformat(dates[-1])
    for tag, arr, is_high in (("H", h, True), ("L", l, False)):
        ix = last_pivot(arr, strength, is_high)
        if ix is None:
            out["a"][tag] = None
            continue
        price = float(arr[ix])
        out["a"][tag] = [dates[ix], round(price, 2), today - ix]
        for i, add in price_to_time_bars(price):
            if ix + add == today:
                out["pt"].append([tag, i, add])
        adate = dt.date.fromisoformat(dates[ix])
        for c in CYCLES:
            if ix + c == today:
                out["cb"].append([tag, c])
            if adate + dt.timedelta(days=c) == today_date:
                out["cd"].append([tag, c])
    return out


def run(hist: pd.DataFrame, payload: dict, sector_csv: str, out_path: str):
    hist = hist.sort_values(["date", "symbol"])
    P = {c: hist.pivot(index="date", columns="symbol", values=c).sort_index()
         for c in ["high", "low", "close", "prev_close", "volume"]}
    close, prev = P["close"], P["prev_close"]
    dates = list(close.index)
    asof = dates[-1]

    # split / bonus adjustment (same method as update.py / screeners.py)
    ratio = (prev / close.shift(1)).fillna(1.0)
    ratio = ratio.where((ratio - 1).abs() > 0.003, 1.0)
    factor = ratio.iloc[::-1].cumprod().iloc[::-1].shift(-1).fillna(1.0)
    aH, aL = P["high"] * factor, P["low"] * factor

    # liquidity: SMA(close * volume, 20) > 3 crore and close > 20 (latest day, raw prices)
    cv20 = (close * P["volume"]).rolling(20, min_periods=20).mean().iloc[-1]
    last_close = close.iloc[-1]
    liquid = (cv20 > LIQ_MIN) & (last_close > MIN_PRICE)

    sectors = load_sectors(sector_csv)
    sec2 = {k: (v[0], v[1]) for k, v in sectors.items()}
    hits = payload["hits"]

    windows, groups, members, shits = {}, {}, {}, {}
    for p in ("w", "m"):
        st = win_start(asof, p)
        ti, ts, syms = top_groups(hits, sec2, st, asof)
        windows[p] = {"start": st, "end": asof}
        groups[p] = {"ind": ti, "sub": ts}
        shits[p] = syms
        ti_set, ts_set = {x[0] for x in ti}, {x[0] for x in ts}
        members[p] = {s for s, (ind, sub) in sec2.items() if ind in ti_set or sub in ts_set}
        if ONLY_SCREENER_HITS:
            members[p] &= {s.upper() for s in syms}

    eligible = sorted(s for s in close.columns
                      if bool(liquid.get(s, False)) and (s.upper() in members["w"] or s.upper() in members["m"]))
    stocks = []
    for sym in eligible:
        hh, ll = aH[sym].dropna(), aL[sym].dropna()
        if hh.empty or hh.index[-1] != asof:
            continue
        ind, sub = sec2.get(sym.upper(), ("", ""))
        rec = {"s": sym, "i": ind, "g": sub, "c": round(float(last_close[sym]), 2),
               "v": round(float(cv20[sym]) / 1e7, 1),
               "f": {p: sym.upper() in members[p] for p in ("w", "m")},
               "sh": {p: sym in shits[p] for p in ("w", "m")},
               "a": {}, "pt": {}, "cb": {}, "cd": {}}
        any_hit = False
        d_s = list(hh.index)
        for L in STRENGTHS:
            r = analyse(hh.values, ll.reindex(hh.index).values, d_s, L)
            rec["a"][str(L)] = r["a"]
            for key in ("pt", "cb", "cd"):
                if r[key]:
                    rec[key][str(L)] = r[key]
                    any_hit = True
        if any_hit:
            stocks.append(rec)

    out = {
        "updated": asof, "demo": False, "strengths": list(STRENGTHS), "cycles": list(CYCLES),
        "liq_min_cr": LIQ_MIN / 1e7, "min_price": MIN_PRICE, "group_screeners": list(GROUP_SCREENERS),
        "windows": windows, "groups": groups,
        "universe": {p: int(sum(1 for s in eligible if s.upper() in members[p])) for p in ("w", "m")},
        "stocks": stocks,
    }
    with open(out_path, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"gann_data.json: {len(stocks)} stocks with a hit today, eligible={len(eligible)}")
    return out
