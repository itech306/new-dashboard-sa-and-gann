"""Daily EOD update: NSE bhavcopy -> MR20 / U4 / D4 / W20 -> data.json.

Run:  python update.py
Needs: pandas, requests.

Files it keeps in this folder:
  data.json        the site's data (oldest first), appended every run
  history.csv.gz   last ~750 trading days of per-stock OHLC/volume (EMA + screeners + Gann). Actions cache me rehti hai.

Definitions (calibrate once against your Chartink numbers, see README):
  universe  same as the Chartink filter: 10-day avg volume x close / 1 crore > 10
            AND close > 10 (rupees)
  MR20      % of universe with adjusted close above its 20-day EMA
  U4 / D4   close up / down 4%+ vs previous close AND volume above previous day
  W20       adjusted close up 20%+ vs 5 trading days ago
Prices are adjusted for splits/bonus using NSE's own previous-close column:
if today's PrevClose differs from yesterday's Close, older prices are rescaled.
"""
import datetime as dt
import io
import json
import os
import sys
import time
import zipfile

import pandas as pd
import requests

from sa_logic import enrich
import gann
import screeners

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data.json")
HIST = os.path.join(HERE, "history.csv.gz")
SECTORS = os.path.join(HERE, "sector_map.csv")      # tumhari sector/industry file (manual update)
SCREENER_OUT = os.path.join(HERE, "screener_data.json")
GANN_OUT = os.path.join(HERE, "gann_data.json")
LISTING = os.path.join(HERE, "listing_dates.csv")   # NSE EQUITY_L.csv se: symbol,listing_date
LISTING_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
FO_CSV = os.path.join(HERE, "fo_list.csv")          # NSE F&O underlyings: symbol
BAND_CSV = os.path.join(HERE, "price_band.csv")     # circuit band: symbol,band (sirf 2 / 5)
FO_URLS = ["https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv", "https://archives.nseindia.com/content/fo/fo_mktlots.csv"]
BAND_ALL = os.path.join(HERE, "price_band_all.csv")   # saare stocks ka band (kal se compare karne ke liye): symbol,band (0 = no band)
BAND_LOG = os.path.join(HERE, "band_changes.csv")    # circuit change history: date,symbol,old,new
BAND_URLS = ["https://nsearchives.nseindia.com/content/equities/sec_list_{dmy}.csv", "https://archives.nseindia.com/content/equities/sec_list_{dmy}.csv"]  # Securities with price band, DDMMYYYY

AVG_TURNOVER_CR = 10  # 10-day avg volume x close, in crore
MIN_PRICE = 10
METHOD = "chartink-v2"  # bump when the calculation changes (forces a recompute)
BASE_END = "2026-10-09"  # last day that comes from the original sheet
U4_PCT = 0.04
WARMUP_DAYS = 1100  # calendar days (~750 trading days): EMA + weekly SMA(50) + cool-off + Gann swing anchors (strength 40, cycles 720)

URLS = [
    # UDiFF format (NSE, from July 2024)
    "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip",
]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "*/*",
    "Referer": "https://www.nseindia.com/",
}
COLS = {  # UDiFF name -> our name (old-format names as fallback)
    "TckrSymb": "symbol", "SYMBOL": "symbol",
    "SctySrs": "series", "SERIES": "series",
    "OpnPric": "open", "OPEN": "open",
    "HghPric": "high", "HIGH": "high",
    "LwPric": "low", "LOW": "low",
    "ClsPric": "close", "CLOSE": "close",
    "PrvsClsgPric": "prev_close", "PREVCLOSE": "prev_close",
    "TtlTradgVol": "volume", "TOTTRDQTY": "volume",
    "TtlTrfVal": "turnover", "TOTTRDVAL": "turnover",
}


def fetch_day(day: dt.date, session: requests.Session):
    """Return a DataFrame for one trading day, or None (holiday / not published)."""
    ymd = day.strftime("%Y%m%d")
    for tpl in URLS:
        url = tpl.format(ymd=ymd)
        for attempt in range(3):
            try:
                r = session.get(url, headers=HEADERS, timeout=30)
            except requests.RequestException:
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 404:
                break
            if r.status_code != 200 or not r.content[:2] == b"PK":
                time.sleep(2 * (attempt + 1))
                continue
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                df = pd.read_csv(z.open(z.namelist()[0]))
            df = df.rename(columns=COLS)
            need = {"symbol", "series", "open", "high", "low", "close", "prev_close", "volume", "turnover"}
            if not need.issubset(df.columns):
                print(f"{day}: unexpected columns {list(df.columns)[:12]}", file=sys.stderr)
                return None
            df = df[df["series"] == "EQ"][["symbol", "open", "high", "low", "close", "prev_close", "volume", "turnover"]].copy()
            df.insert(0, "date", day.isoformat())
            return df
    return None


def refresh_listing(session):
    """NSE ki EQUITY_L.csv se listing dates. Fail ho to purani listing_dates.csv chalti rahegi."""
    try:
        r = session.get(LISTING_URL, headers=HEADERS, timeout=30)
        if r.status_code != 200:
            print(f"EQUITY_L.csv nahi mili (HTTP {r.status_code}), purani listing_dates.csv use hogi.", file=sys.stderr)
            return
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = [c.strip().upper() for c in df.columns]
        if not {"SYMBOL", "DATE OF LISTING"}.issubset(df.columns):
            print(f"EQUITY_L.csv ke columns alag hain: {list(df.columns)}", file=sys.stderr)
            return
        out = pd.DataFrame({"symbol": df["SYMBOL"].astype(str).str.strip(),
                            "listing_date": df["DATE OF LISTING"].astype(str).str.strip()})
        out.to_csv(LISTING, index=False)
        print(f"listing_dates.csv: {len(out)} symbols")
    except Exception as e:  # noqa: BLE001
        print(f"listing dates update fail: {e}", file=sys.stderr)


def log_band_changes(full, day):
    """Kal ke band se compare karke jinka band badla unhe band_changes.csv me jodo (date = sec_list file ki date)."""
    if not os.path.exists(BAND_ALL):
        print("price_band_all.csv pehli baar bani: aaj se changes track honge.")
        return
    old = pd.read_csv(BAND_ALL).set_index("symbol")["band"]
    new = full.set_index("symbol")["band"]
    j = pd.concat([old.rename("old"), new.rename("new")], axis=1, join="inner")
    ch = j[j["old"] != j["new"]].reset_index()
    if ch.empty:
        return
    ch.insert(0, "date", day.isoformat())
    log = pd.read_csv(BAND_LOG) if os.path.exists(BAND_LOG) else pd.DataFrame(columns=["date", "symbol", "old", "new"])
    log = pd.concat([log, ch[["date", "symbol", "old", "new"]]], ignore_index=True).drop_duplicates(["date", "symbol"], keep="last")
    log.sort_values(["date", "symbol"]).to_csv(BAND_LOG, index=False)
    print(f"band_changes.csv: {len(ch)} circuit changes ({day})")


def refresh_fo_band(session):
    """F&O list + price band (2% / 5% circuit) NSE se. Fail ho to purani CSV files chalti rahengi."""
    try:
        r = None
        for u in FO_URLS:
            r = session.get(u, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                break
        if r is not None and r.status_code == 200:
            df = pd.read_csv(io.StringIO(r.text))
            df.columns = [c.strip().upper() for c in df.columns]
            col = "SYMBOL" if "SYMBOL" in df.columns else df.columns[1]
            syms = df[col].astype(str).str.strip()
            syms = syms[syms.str.match(r"^[A-Z0-9&\-]+$") & (syms != "SYMBOL")].drop_duplicates()
            # index rows (NIFTY, BANKNIFTY ...) bhi list me aate hain, wo screener me kabhi nahi dikhte, harmless
            if len(syms) > 50:
                pd.DataFrame({"symbol": syms}).to_csv(FO_CSV, index=False)
                print(f"fo_list.csv: {len(syms)} symbols")
            else:
                print(f"fo_mktlots.csv me kam symbols ({len(syms)}), purani fo_list.csv use hogi.", file=sys.stderr)
        else:
            print(f"fo_mktlots.csv nahi mili (HTTP {r.status_code}), purani fo_list.csv use hogi.", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"F&O list update fail: {e}", file=sys.stderr)
    # price band: aaj se peeche 7 din tak koi published file dhundho
    try:
        for back in range(0, 8):
            day = dt.date.today() - dt.timedelta(days=back)
            r = None
            for u in BAND_URLS:
                r = session.get(u.format(dmy=day.strftime("%d%m%Y")), headers=HEADERS, timeout=30)
                if r.status_code == 200:
                    break
            if r is None or r.status_code != 200:
                continue
            df = pd.read_csv(io.StringIO(r.text))
            df.columns = [c.strip().upper() for c in df.columns]
            bcol = next((c for c in df.columns if "BAND" in c), None)
            scol = next((c for c in df.columns if c in ("SYMBOL", "SECURITY ID")), df.columns[0])
            if bcol is None:
                print(f"sec_list columns alag hain: {list(df.columns)}", file=sys.stderr)
                return
            ser = next((c for c in df.columns if c == "SERIES"), None)
            if ser:
                df = df[df[ser].astype(str).str.strip() == "EQ"]
            band = pd.to_numeric(df[bcol].astype(str).str.replace("%", "", regex=False).str.strip(), errors="coerce")
            full = pd.DataFrame({"symbol": df[scol].astype(str).str.strip(), "band": band.fillna(0).astype(int)})
            full = full.drop_duplicates("symbol")
            log_band_changes(full, day)
            full.to_csv(BAND_ALL, index=False)
            out = full[full["band"].isin([2, 5])]
            out.to_csv(BAND_CSV, index=False)
            print(f"price_band.csv: {len(out)} stocks in 2%/5% band ({day})")
            return
        print("sec_list (price band) file nahi mili, purani price_band.csv use hogi.", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"price band update fail: {e}", file=sys.stderr)


def load_history():
    cols = ["date", "symbol", "open", "high", "low", "close", "prev_close", "volume", "turnover"]
    if os.path.exists(HIST):
        h = pd.read_csv(HIST)
        if set(cols).issubset(h.columns):
            return h
        print("history.csv.gz me open/high/low nahi hai, dobara download hoga.")
    return pd.DataFrame(columns=cols)


def compute_day(hist: pd.DataFrame, day: str):
    """Compute MR20/U4/D4/W20/universe for `day` using history up to and including it."""
    h = hist[hist["date"] <= day]
    close = h.pivot(index="date", columns="symbol", values="close").sort_index()
    prev = h.pivot(index="date", columns="symbol", values="prev_close").sort_index()
    vol = h.pivot(index="date", columns="symbol", values="volume").sort_index()
    turn = h.pivot(index="date", columns="symbol", values="turnover").sort_index()

    # split/bonus adjustment: ratio of NSE's prev close to our stored previous close
    ratio = (prev / close.shift(1)).fillna(1.0)
    ratio = ratio.where((ratio - 1).abs() > 0.003, 1.0)
    factor = ratio.iloc[::-1].cumprod().iloc[::-1].shift(-1).fillna(1.0)
    adj = close * factor

    ema = adj.ewm(span=20, adjust=False, min_periods=20).mean()
    avg_vol10 = vol.rolling(10, min_periods=10).mean().loc[day]
    universe = (avg_vol10 * close.loc[day] / 1e7 > AVG_TURNOVER_CR) & (close.loc[day] > MIN_PRICE)
    last_adj, last_ema = adj.loc[day], ema.loc[day]
    valid = universe & last_ema.notna() & last_adj.notna()
    mr20 = round(100 * (last_adj[valid] > last_ema[valid]).mean(), 1)

    ret = close.loc[day] / prev.loc[day] - 1
    vol_up = vol.loc[day] > vol.shift(1).loc[day]
    u4 = int((universe & (ret >= U4_PCT) & vol_up).sum())
    d4 = int((universe & (ret <= -U4_PCT) & vol_up).sum())

    if len(adj) > 5:
        w = adj.loc[day] / adj.shift(5).loc[day] - 1
        w20 = int((universe & (w >= 0.20)).sum())
    else:
        w20 = 0
    return {"date": day, "MR20": float(mr20), "U4": u4, "D4": d4, "W20": w20,
            "universe": int(universe.sum())}


def main():
    with open(DATA) as f:
        payload = json.load(f)
    rows = payload["rows"]
    if payload.get("method") != METHOD:
        # calculation changed: keep the sheet's history, recompute everything after it
        rows = [r for r in rows if r["date"] <= BASE_END]
    last = dt.date.fromisoformat(rows[-1]["date"])
    today = dt.date.today()

    hist = load_history()
    have = set(hist["date"].unique())
    start = today - dt.timedelta(days=WARMUP_DAYS)

    session = requests.Session()
    session.get("https://www.nseindia.com/", headers=HEADERS, timeout=30)  # cookies
    refresh_listing(session)
    refresh_fo_band(session)
    new_frames, fetched = [], []
    d = start
    while d <= today:
        if d.weekday() < 5 and d.isoformat() not in have:
            df = fetch_day(d, session)
            if df is not None:
                new_frames.append(df)
                fetched.append(d.isoformat())
            time.sleep(1)
        d += dt.timedelta(days=1)
    if new_frames:
        hist = pd.concat([hist] + new_frames, ignore_index=True)
    cutoff = (today - dt.timedelta(days=WARMUP_DAYS + 20)).isoformat()
    hist = hist[hist["date"] >= cutoff].sort_values(["date", "symbol"])
    if hist.empty:
        sys.exit("NSE se koi bhavcopy download nahi hui (shayad NSE ne GitHub ka IP block kiya). Log upar dekho.")
    hist = hist.round({"open": 2, "high": 2, "low": 2, "close": 2, "prev_close": 2, "volume": 0, "turnover": 0})
    hist.to_csv(HIST, index=False, compression="gzip")

    todo = [x for x in sorted(hist["date"].unique()) if x > rows[-1]["date"]]
    if todo or payload.get("method") != METHOD:
        update_monitor(rows, hist, todo)
    else:
        print("No new trading days for MR20 monitor.")
    # screeners: har run me dobara (sector_map.csv badli ho to naya mapping bhi lag jaye)
    # Strong Sector / Gann me dikkat aaye to bhi market monitor (data.json) ka kaam na rukey
    try:
        sp = screeners.run(hist, SECTORS, SCREENER_OUT, LISTING, FO_CSV, BAND_CSV, BAND_LOG)
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(f"::warning::screener_data.json nahi bana: {e}")
        return
    try:
        gann.run(hist, sp, SECTORS, GANN_OUT)
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(f"::warning::gann_data.json nahi bana: {e}")


def update_monitor(rows, hist, todo):
    base = [{k: r[k] for k in ("date", "MR20", "U4", "D4", "W20", "universe")} for r in rows]
    for day in todo:
        base.append(compute_day(hist, day))
        print("added", base[-1])
    full = enrich(base)
    with open(DATA, "w") as f:
        json.dump({"updated": full[-1]["date"], "method": METHOD, "rows": full}, f, separators=(",", ":"))


if __name__ == "__main__":
    main()
