"""Setups to Focus: 6 scans ka "roz kitne stocks aaye" count -> setups_data.json.

setups_data.json me 2015 se ab tak ki history pehle se rakhi hai (seed). Har run me yeh sirf naye dino
(jo file me nahi hain) ke counts history.csv.gz se nikaal ke jod deta hai. Purane counts kabhi nahi badalte.

Row = [date, count, thrust_mask]. thrust_mask ke bit 0..5 = gap 15..20 wale thrust. Spike aur "x avg" page par
hi nikalte hain (count se). Thrust: count >= 2.5x pichle 5 din ka avg (Breakout: 1.6x) aur count >= 20; do thrust
ke beech kam se kam G trading din; gap ke andar bada count rakhte hain (greedy). Purane masks freeze rehte hain,
sirf aakhri 20 din ke masks har run me dobara nikalte hain (naya bada din aaye to pichla chhota hat sake).
"""
import json
import os

import numpy as np
import pandas as pd

GAPS = (15, 16, 17, 18, 19, 20)
REFRESH = 20          # itne aakhri din ke thrust masks har run me dobara
MIN_COUNT = 20        # thrust ke liye kam se kam stocks
NAMES = ["Bottom Bounce", "Pullback", "Breakout", "Reversal 2.0", "Nice Bottom", "Market Top"]


def _wide(h, col):
    return h.pivot_table(index="date", columns="symbol", values=col, aggfunc="last").sort_index()


def _adjusted(h):
    """split / bonus adjust (same method as screeners.py / gann.py): prev_close / pichla close ka ratio."""
    P = {k: _wide(h, k) for k in ("open", "high", "low", "close", "prev_close", "volume")}
    ratio = (P["prev_close"] / P["close"].shift(1)).fillna(1.0)
    ratio = ratio.where((ratio - 1).abs() > 0.003, 1.0)
    factor = ratio.iloc[::-1].cumprod().iloc[::-1].shift(-1).fillna(1.0)
    return (P["open"] * factor, P["high"] * factor, P["low"] * factor, P["close"] * factor, P["volume"])


def scan_counts(h):
    """Har trading date ke liye 6 scans ka count (DataFrame: date x scan)."""
    O, H, L, C, V = _adjusted(h)
    T = C * V
    rng = H - L
    body = (O - C).abs()
    mid = (O + C) / 2

    # 1 Bottom Bounce
    a = (body > 0.10 * rng) & (body < 0.30 * rng) & (mid - L > 0.70 * rng) & (L == L.rolling(5).min())
    b = (body > 0.05 * rng) & (body < 0.20 * rng) & (mid - L < 0.30 * rng) & (H == H.rolling(5).max())
    bb = (a | b) & (T.rolling(50).mean() > 30_000_000)

    # 2 Pullback
    e9, e20 = C.ewm(span=9, adjust=False).mean(), C.ewm(span=20, adjust=False).mean()
    pb = (e9 > e20) & (V > 100000) & (O > 50) & (e9 > C)

    # 3 Breakout: pichle poore calendar month ka R1
    ym = pd.Series(C.index.str[:7], index=C.index)
    mh, ml = H.groupby(ym).max(), L.groupby(ym).min()
    mc = C.groupby(ym).last()
    r1 = 2 * (mh + ml + mc) / 3 - ml
    r1 = r1.shift(1)                                   # pichla mahina
    R1 = r1.reindex(ym.values)
    R1.index = C.index
    bo = (C < R1) & (C < 0.99 * R1) & (C > 0.94 * R1)

    # 4 Reversal 2.0
    c1, c2, c3, c4, c5 = (C.shift(k) for k in range(1, 6))
    rv = (C > O) & (c1 < c2) & (c2 < c3) & (c3 < c4) & (c4 < c5) & (O > 100) & (V > 30000)

    # 5 Nice Bottom (Market Cap >= 100 data me nahi, Close <= SMA(200) band tha: dono nahi lagaye)
    nb = (C >= 20) & (L == L.rolling(100).min())

    # 6 Market Top
    d = C.diff()
    rs = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean() / (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + rs)
    up = lambda k: C.shift(k) > O.shift(k)
    mt = ((C > O) & up(1) & up(2) & (rsi > 50) & (C.rolling(5).mean() > C.rolling(20).mean())
          & (H.shift(1) > H.shift(2)) & (H.shift(2) > H.shift(3))
          & (V > V.rolling(20).mean()) & (T.rolling(20).mean() > 20_000_000))

    out = pd.DataFrame({n: m.sum(axis=1) for n, m in zip(NAMES, (bb, pb, bo, rv, nb, mt))})
    return out


def valid_dates(h):
    """Jin dates par stocks ki sankhya median ke 60% se kam ho (holiday / special session), unhe hatao."""
    n = h.groupby("date")["symbol"].nunique()
    return set(n[n >= 0.6 * n.median()].index)


def thrust_masks(rows, mult, frozen):
    """rows: [[date, count, mask], ...]. rows[:frozen] ke masks nahi badalte, baaki dobara nikalte hain."""
    n = len(rows)
    c = [r[1] for r in rows]
    cand = [i for i in range(max(5, frozen), n)
            if c[i] >= MIN_COUNT and c[i] >= mult * (sum(c[i - 5:i]) / 5)]
    cand.sort(key=lambda i: (-c[i], i))
    for i in range(frozen, n):
        rows[i][2] = 0
    for k, g in enumerate(GAPS):
        acc = [i for i in range(frozen) if rows[i][2] >> k & 1]
        for i in cand:
            if all(abs(i - j) >= g for j in acc):
                acc.append(i)
                rows[i][2] |= 1 << k
    return rows


def run(hist, out_path):
    if not os.path.exists(out_path):
        print("setups_data.json nahi mila: repo me seed file honi chahiye.")
        return None
    with open(out_path, encoding="utf-8") as f:
        data = json.load(f)
    last = max(s["rows"][-1][0] for s in data["scans"])
    h = hist[hist["date"].isin(valid_dates(hist))]
    if h["date"].max() <= last:
        print(f"setups_data.json: naya din nahi hai (last {last})")
        return data
    counts = scan_counts(h)
    new_dates = [d for d in counts.index if d > last]
    for s in data["scans"]:
        col = counts[s["name"]]
        for d in new_dates:
            s["rows"].append([d, int(col[d]), 0])
        s["rows"].sort(key=lambda r: r[0])
        s["rows"] = thrust_masks(s["rows"], s.get("mult", 2.5), max(0, len(s["rows"]) - REFRESH - len(new_dates)))
    data["updated"] = new_dates[-1]
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"), ensure_ascii=False)
    print(f"setups_data.json: {len(new_dates)} naye din ({new_dates[0]} se {new_dates[-1]})")
    return data
