"""Screener engine: 7 Chartink-style screeners + cool-off + sector join -> screener_data.json.

Input  : per-stock daily history (date, symbol, open, high, low, close, prev_close, volume, turnover)
         from update.py (history.csv.gz) and sector_map.csv (your manual sector/industry file).
Output : screener_data.json, read by screeners.html.

Screeners (conditions copied from the Chartink queries):
  d4      4% gain, daily           no cool-off (har din ki har hit dikhti hai)
  m14     50% in 14 days           cool-off 14 trading days
  m2      50% in 2 months (40d)    cool-off 40 trading days
  w5_20   20% in 5 days            cool-off 5 trading days
  w5_13   13% in 5 days            cool-off 5 trading days
  wk13    13% in a week            sirf completed week (Friday), cool-off 1 week
  wk20    20% in a week            sirf completed week (Friday), cool-off 1 week

Cool-off rule: jis din stock pehli baar dikhta hai, wahi se cool-off shuru. Agle N periods
tak wo stock us screener me dobara nahi dikhta (chahe raw condition true rahe). N periods
ke baad hi dobara dikh sakta hai. Cool-off sirf dikhaye gaye hits se ginta hai.
"""
import csv
import datetime as dt
import json
import os

import numpy as np
import pandas as pd

MIN_PRICE = 20
WEEK_MIN_PERIODS = 10   # weekly volume SMA(50) ke liye kam se kam itne weeks ka data
IPO_DAYS = 365          # itne din ke andar listed stock "IPO" maana jaata hai
IPO_RELAX_SMA = False   # True: SMA50 ke liye sirf 10 din ka data bhi chalega (naye IPO ke liye)
KEEP_DAYS = 100         # screener_data.json me itne calendar days ke hits rakhte hain

SCREENERS = [
    {"id": "d4",    "name": "4% Gain (Daily)",  "short": "4% Daily",      "cooloff": 0,  "unit": "day",  "kind": "daily"},
    {"id": "w5_20", "name": "20% in 5 Days",    "short": "20% in 5 Days", "cooloff": 5,  "unit": "day",  "kind": "cool"},
    {"id": "w5_13", "name": "13% in 5 Days",    "short": "13% in 5 Days", "cooloff": 5,  "unit": "day",  "kind": "cool"},
    {"id": "m14",   "name": "50% in 14 Days",   "short": "50% in 14 Days", "cooloff": 14, "unit": "day",  "kind": "cool"},
    {"id": "m2",    "name": "50% in 2 Months",  "short": "50% in 2 Months", "cooloff": 40, "unit": "day",  "kind": "cool"},
    {"id": "wk13",  "name": "13% in a Week",   "short": "13% in a Week", "cooloff": 1,  "unit": "week", "kind": "week"},
    {"id": "wk20",  "name": "20% in a Week",   "short": "20% in a Week", "cooloff": 1,  "unit": "week", "kind": "week"},
]


def cooloff(hit: pd.DataFrame, n: int) -> pd.DataFrame:
    """Keep a hit only if the stock was not shown in the previous n rows."""
    if n <= 0:
        return hit
    h = hit.values
    out = np.zeros_like(h, dtype=bool)
    last = np.full(h.shape[1], -10**9)
    for i in range(h.shape[0]):
        ok = h[i] & ((i - last) > n)
        out[i] = ok
        last = np.where(ok, i, last)
    return pd.DataFrame(out, index=hit.index, columns=hit.columns)


def load_sectors(path):
    m = {}
    if path and os.path.exists(path):
        with open(path, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                k = (r.get("Security Id") or "").strip().upper()
                if k:
                    m[k] = ((r.get("Industry New Name") or "").strip(), (r.get("ISubgroup Name") or "").strip(),
                            parse_date(r.get("Listing Date")))
    return m


def parse_date(v):
    """'08-JAN-2024', '2024-01-08' ya '08/01/2024' -> 'YYYY-MM-DD' (nahi samjha to '')."""
    v = (v or "").strip()
    for f in ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return dt.datetime.strptime(v.title() if "%b" in f else v, f).date().isoformat()
        except ValueError:
            pass
    return ""


def load_fo(path):
    """fo_list.csv (symbol) - update.py NSE ki F&O lot-size file se banata hai."""
    out = set()
    if path and os.path.exists(path):
        with open(path, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                k = (r.get("symbol") or "").strip().upper()
                if k:
                    out.add(k)
    return out


def load_band(path):
    """price_band.csv (symbol,band) - sirf 2 ya 5 (% circuit) wale stocks rakhte hain."""
    m = {}
    if path and os.path.exists(path):
        with open(path, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                k = (r.get("symbol") or "").strip().upper()
                try:
                    b = int(float(r.get("band")))
                except (TypeError, ValueError):
                    continue
                if k and b in (2, 5):
                    m[k] = b
    return m


def load_band_changes(path, cutoff):
    """band_changes.csv (date,symbol,old,new) -> [[date, symbol, old, new], ...] cutoff ke baad ke."""
    out = []
    if path and os.path.exists(path):
        with open(path, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                try:
                    d, s, o, n = r["date"].strip(), r["symbol"].strip(), int(float(r["old"])), int(float(r["new"]))
                except (KeyError, TypeError, ValueError, AttributeError):
                    continue
                if d >= cutoff and s:
                    out.append([d, s, o, n])
    return sorted(out)


def load_listing(path):
    """listing_dates.csv (symbol,listing_date) - update.py NSE ki EQUITY_L.csv se banata hai."""
    m = {}
    if path and os.path.exists(path):
        with open(path, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                k = (r.get("symbol") or "").strip().upper()
                d = parse_date(r.get("listing_date"))
                if k and d:
                    m[k] = d
    return m


def compute_hits(hist: pd.DataFrame):
    """Return {screener_id: (shown_bool_df, pct_df)} plus the list of dates."""
    hist = hist.sort_values(["date", "symbol"])
    P = {c: hist.pivot(index="date", columns="symbol", values=c).sort_index()
         for c in ["open", "high", "low", "close", "prev_close", "turnover"]}
    close, prev, turn = P["close"], P["prev_close"], P["turnover"]

    # split / bonus adjustment (same method as update.py)
    ratio = (prev / close.shift(1)).fillna(1.0)
    ratio = ratio.where((ratio - 1).abs() > 0.003, 1.0)
    factor = ratio.iloc[::-1].cumprod().iloc[::-1].shift(-1).fillna(1.0)
    aO, aH, aL, aC = (P[k] * factor for k in ("open", "high", "low", "close"))

    t20 = turn.rolling(20, min_periods=20).mean()
    # NOTE: naye IPO ke paas 50 din ka data nahi hota, isliye 4% screener me wo pehle ~50 din nahi aate
    # (Chartink me bhi yahi hota hai). IPO_RELAX_SMA=True karne par ye rok hat jaati hai.
    t50 = turn.rolling(50, min_periods=(10 if IPO_RELAX_SMA else 50)).mean()
    liquid = (close > MIN_PRICE) & (t20 > 3e7)
    res = {}

    # 1) 4% gain, daily, no cool-off. 4.99-5.01% moves (5% circuit stocks) are excluded.
    pct = (close - prev) / prev * 100
    d4 = (close > prev * 1.04) & (close > MIN_PRICE) & (t50 > 3e7) & ~((pct >= 4.99) & (pct <= 5.01))
    res["d4"] = (cooloff(d4, 0), pct)

    # 2) 50% in 14 days: close / lowest low of last 14 days >= 1.5
    low14 = aL.rolling(14, min_periods=14).min()
    m14 = (aC / low14 >= 1.5) & liquid
    res["m14"] = (cooloff(m14, 14), (aC / low14 - 1) * 100)

    # 3) 50% in 2 months: close >= close 40 trading days ago * 1.5, avg turnover(20d) >= 15 cr
    m2 = (t20 >= 1.5e8) & (aC >= aC.shift(40) * 1.5) & (close > MIN_PRICE)
    res["m2"] = (cooloff(m2, 40), (aC / aC.shift(40) - 1) * 100)

    # 4/5) 20% / 13% in 5 days: highest close of last 5 days >= close 5 days ago * 1.20 / 1.13
    max5 = aC.rolling(5, min_periods=5).max()
    for sid, mult in (("w5_20", 1.20), ("w5_13", 1.13)):
        h = (max5 >= aC.shift(5) * mult) & liquid
        res[sid] = (cooloff(h, 5), (max5 / aC.shift(5) - 1) * 100)

    # 6/7) weekly: completed weeks only (week ends Friday). Evaluated on the week's last trading day.
    dates = list(close.index)
    latest = dt.date.fromisoformat(dates[-1])
    wk = pd.to_datetime(pd.Series(dates)).dt.to_period("W-FRI").values
    g = lambda df, how: getattr(df.groupby(wk), how)()
    wo, wh = g(aO, "first"), g(aH, "max")
    wt, wclose = g(turn, "sum"), g(close, "last")
    wend = pd.Series(dates).groupby(wk).last()
    wt50 = wt.rolling(50, min_periods=WEEK_MIN_PERIODS).mean()
    wk_liquid = (wclose < 10000) & (wt50 / 5 / 1e7 > 3)
    complete = pd.Series([p.end_time.date() <= latest for p in wo.index], index=wo.index)
    for sid, mult in (("wk13", 1.13), ("wk20", 1.20)):
        h = (wh > wo * mult) & wk_liquid
        h = h.loc[complete]
        p = ((wh / wo - 1) * 100).loc[complete]
        shown = cooloff(h, 1)
        idx = wend.loc[shown.index].values
        shown.index = idx
        p.index = idx
        res[sid] = (shown, p)
    # extra columns for the page filters: raw close and 50-day avg turnover (crore), same basis as Gap Up
    extra = {"close": close, "t50cr": turn.rolling(50, min_periods=20).mean() / 1e7}
    return res, dates, extra


def run(hist: pd.DataFrame, sector_csv: str, out_path: str, listing_csv: str = None,
        fo_csv: str = None, band_csv: str = None, band_log_csv: str = None):
    res, dates, extra = compute_hits(hist)
    sectors = load_sectors(sector_csv)
    listing = load_listing(listing_csv)
    fo_set, band_map = load_fo(fo_csv), load_band(band_csv)
    hist_syms = set(hist["symbol"].unique())
    first_seen = hist.groupby("symbol")["date"].min()
    hist_start = dates[0]
    early = (dt.date.fromisoformat(hist_start) + dt.timedelta(days=10)).isoformat()
    latest = dates[-1]
    cutoff = (dt.date.fromisoformat(latest) - dt.timedelta(days=KEEP_DAYS)).isoformat()
    hits, used = [], set()
    for sid, (shown, pct) in res.items():
        sub = shown.loc[shown.index >= cutoff]
        r, c = np.nonzero(sub.values)
        for i, j in zip(r, c):
            day, sym = sub.index[i], sub.columns[j]
            v = pct.loc[day, sym]
            c, t = extra["close"].at[day, sym], extra["t50cr"].at[day, sym]
            # [date, screener, symbol, move %, close on that day, 50d avg turnover in cr]
            hits.append([day, sid, sym, None if pd.isna(v) else round(float(v), 1),
                         None if pd.isna(c) else round(float(c), 2), None if pd.isna(t) else round(float(t), 1)])
            used.add(sym)
    hits.sort(key=lambda x: (x[0], x[1], x[2]))
    sec = {}
    for s in sorted(used):
        ind, sub, ld = (list(sectors.get(s.upper(), ["", "", ""])) + ["", "", ""])[:3]
        # listing date: 1) sector_map.csv "Listing Date"  2) NSE EQUITY_L.csv  3) history me pehla din
        ld = ld or listing.get(s.upper(), "")
        if not ld and s in first_seen.index and first_seen[s] > early:
            ld = first_seen[s]
        sec[s] = [ind, sub, ld]
    unmapped = sorted(s for s, v in sec.items() if not v[0])
    payload = {
        "updated": latest,
        "ipo_days": IPO_DAYS,
        "demo": False,
        "screeners": SCREENERS,
        "dates": [d for d in dates if d >= cutoff],
        "sectors": sec,
        # F&O + 2%/5% circuit: saare listed symbols (screener, Gann aur Gap Up teeno pages ke liye)
        "fo": sorted(s for s in hist_syms if s.upper() in fo_set),
        "band": {s: band_map[s.upper()] for s in sorted(hist_syms) if s.upper() in band_map},
        "unmapped": unmapped,
        "band_changes": load_band_changes(band_log_csv, (dt.date.fromisoformat(latest) - dt.timedelta(days=200)).isoformat()),  # [date, symbol, old %, new %]; 0 = no band
        "hits": hits,
    }
    with open(out_path, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"screener_data.json: {len(hits)} hits, {len(unmapped)} unmapped symbols, "
          f"{len(payload['fo'])} F&O, {len(payload['band'])} circuit-band (2/5%), {len(payload['band_changes'])} band changes")
    return payload
