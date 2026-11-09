"""Chart data for the hover/expand chart  ->  gann_history/chart_data.json

Swing Master v2 indicators are computed here (pandas/numpy), the browser only draws.

File format (version 1)
  {"v":1,"n":126,"d":["2026-05-04",...],            # dates once, oldest first (last n trading days)
   "s":{"SYM":[c0,[C],[O],[H],[L],[F]], ...}}        # one array per stock, aligned to the END of "d"
  Prices are split/bonus adjusted, in paise (int). With n_i = len(C):
      close_i = c0 + sum(C[0..i])      (C[0] = 0)
      open_i  = close_i + O[i]         high_i = close_i + H[i]        low_i = close_i - L[i]
  F[i] packs the flags of bar i in one int:
      bits 0-3 bar colour (0 default,1 MB up,2 MB down,3 inside+NR,4 NR7&NR21,5 NR7,6 NR21,7 inside,8 ANTS)
      bits 4-5 volume flag (0 none,1 HVE,2 HVY,3 HVQ)   bit 6 pocket pivot   bit 7 episodic pivot
      bits 8-9 HT (0 none,1 purple,2 red)               bits 10-11 TI (0 none,1 green,2 red)
      bit 12 50 SMA downside extension
"""
import json
import os

import numpy as np
import pandas as pd

N_BARS = 126
EP_VOL = 9_000_000


def _rma(x, n):
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    v = x[:n]
    if np.isnan(v).any():
        return out
    out[n - 1] = v.mean()
    for i in range(n, len(x)):
        out[i] = out[i - 1] + (x[i] - out[i - 1]) / n if not np.isnan(x[i]) else out[i - 1]
    return out


def _ht(turn):
    """HT purple / red signals with min 2 bars spacing, separate counters, red has priority."""
    s = pd.Series(turn)
    s10, s20 = s.rolling(10).mean(), s.rolling(20).mean()
    cp = (s10 >= s10.rolling(15).max()).values
    cr = (s20 >= s20.rolling(63).max()).values
    out = np.zeros(len(s), dtype=np.int64)
    lp = lr = -10**9
    for i in range(len(s)):
        red = bool(cr[i]) and i - lr >= 2
        if red:
            out[i] = 2
            lr = i
            continue
        if bool(cp[i]) and i - lp >= 2:
            out[i] = 1
            lp = i
    return out


def flags_for(o, h, l, c, v, raw_c):
    """All per-bar flags for one stock (arrays on the stock's full adjusted history)."""
    n = len(c)
    C, H, L, V = (pd.Series(a) for a in (c, h, l, v))
    pc, ph, pl, pv = C.shift(1), H.shift(1), L.shift(1), V.shift(1)
    vol_ok = (V > pv) & (V >= 100000)
    mbu = ((C / pc) >= 1.04) & vol_ok
    mbd = ((C / pc) <= 0.96) & vol_ok
    inside = (H < ph) & (L > pl)
    rng = H - L
    nr7 = rng < rng.shift(1).rolling(7).min()
    nr21 = rng < rng.shift(1).rolling(21).min()
    ti = C.rolling(7).mean() / C.rolling(65).mean()
    chg = (C / pc - 1) * 100
    ants = (ti >= 1.05) & (chg >= -0.4) & (chg <= 0.4)
    code = np.zeros(n, dtype=np.int64)
    for k, m in reversed([(1, mbu), (2, mbd), (3, inside & (nr7 | nr21)), (4, nr7 & nr21), (5, nr7),
                          (6, nr21), (7, inside), (8, ants)]):
        code = np.where(m.fillna(False).values, k, code)          # first match wins (applied last-to-first)
    # volume flags
    hv = np.zeros(n, dtype=np.int64)
    vpos = (V > 0).values
    hve = vpos & (V >= V.cummax()).values & (np.arange(n) >= 1)
    r252 = V.rolling(252).max()
    r63 = V.rolling(63).max()
    hvy = vpos & (V >= r252).fillna(False).values
    hvq = vpos & (V >= r63).fillna(False).values
    hv = np.where(hvq, 3, hv)
    hv = np.where(hvy, 2, hv)
    hv = np.where(hve, 1, hv)
    pp = (V > V.shift(1).rolling(10).max()) & (C > pc)
    ep = V > EP_VOL
    ht = _ht(np.asarray(raw_c, dtype=float) * np.asarray(v, dtype=float))
    tis = np.where((ti >= 1.05).fillna(False).values, 1, np.where((ti <= 0.95).fillna(False).values, 2, 0))
    tr = pd.concat([H - L, (H - pc).abs(), (L - pc).abs()], axis=1).max(axis=1)
    tr.iloc[0] = (H - L).iloc[0]
    atr = _rma(tr.values, 14)
    ext = ((C - C.rolling(50).mean()).values / atr) <= -3
    ext = np.where(np.isnan(ext.astype(float)), False, ext)
    return (code | (hv << 4) | (pp.fillna(False).values.astype(np.int64) << 6) | (ep.values.astype(np.int64) << 7)
            | (ht << 8) | (tis << 10) | (np.asarray(ext, dtype=np.int64) << 12))


def build(hist: pd.DataFrame, symbols, out_path: str, n_bars: int = N_BARS):
    """hist: date,symbol,open,high,low,close,prev_close,volume. symbols: iterable to include."""
    want = set(symbols)
    h = hist[hist["symbol"].isin(want)].sort_values(["symbol", "date"])
    cal = sorted(hist["date"].unique())[-n_bars:]
    out = {}
    for sym, g in h.groupby("symbol", sort=True):
        try:
            g = g.drop_duplicates("date").reset_index(drop=True)
            close, prev = g["close"].astype(float), g["prev_close"].astype(float)
            ratio = (prev / close.shift(1)).fillna(1.0)               # same factor method as screeners.py / gann.py
            ratio = ratio.where((ratio - 1).abs() > 0.003, 1.0)
            f = ratio.iloc[::-1].cumprod().iloc[::-1].shift(-1).fillna(1.0).values
            o, hi, lo, c = (g[k].astype(float).values * f for k in ("open", "high", "low", "close"))
            v = g["volume"].astype(float).fillna(0).values
            fl = flags_for(o, hi, lo, c, v, g["close"].astype(float).values)
            df = pd.DataFrame({"o": o, "h": hi, "l": lo, "c": c, "f": fl}, index=g["date"])
            df = df[df.index.isin(cal)]
            if df.empty:
                continue
            df = df.reindex([d for d in cal if d >= df.index[0]])
            df[["o", "h", "l", "c"]] = df[["o", "h", "l", "c"]].ffill()
            df["f"] = df["f"].fillna(0)
            P = lambda a: np.round(a * 100).astype(np.int64)
            cc = P(df["c"].values)
            oo, hh, ll = P(df["o"].values), P(df["h"].values), P(df["l"].values)
            dc = np.diff(cc, prepend=cc[0])
            out[sym] = [int(cc[0]), dc.tolist(), (oo - cc).tolist(), (hh - cc).tolist(), (cc - ll).tolist(),
                        df["f"].astype(np.int64).tolist()]
        except Exception:                                              # never break the daily job for one stock
            continue
    payload = {"v": 1, "n": n_bars, "d": cal, "s": out}
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    print(f"chart_data.json: {len(out)} stocks, {os.path.getsize(out_path) / 1e6:.2f} MB")
    return payload
