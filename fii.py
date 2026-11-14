"""FII/FPI investor COUNT (not %) per stock -> fii_data.json

Source: NSE quarterly shareholding-pattern filing (XBRL). Row "Foreign Portfolio Investors"
(Category I + Category II), column "No. of shareholders".

Run:  python fii.py          (workflow isse alag step me chalata hai, update.py ko touch nahi karta)
Env:  FII_MAX_PER_RUN=300    ek run me kitne stocks fetch karne hain (baaki agle run me, cache jaisa)
      FII_SYMBOLS=HDFCBANK,INFY   sirf ye symbols (testing ke liye)

fii_data.json: {"updated": "2026-11-14", "stocks": {"HDFCBANK": [3450, 3330, "2026-09-30", "2026-11-14"]}}
                                                      [count, previous quarter count, filing quarter, last checked]
Pehle run me sector_map.csv ke saare ~2300 stocks 8-10 din me bhar jaate hain (300/run).
Uske baad sirf naya quarterly filing aane par refresh hota hai. NSE kuch badle to fii_debug.txt dekho.
"""
import csv
import datetime as dt
import json
import os
import re
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "fii_data.json")
DEBUG = os.path.join(HERE, "fii_debug.txt")
SECTORS = os.path.join(HERE, "sector_map.csv")
MAX_PER_RUN = int(os.environ.get("FII_MAX_PER_RUN", "300"))
RECHECK_DAYS = 7
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern",
}
LIST_URL = "https://www.nseindia.com/api/corporate-share-holdings-master?index=equities&symbol={sym}"


def quarter_end(today):
    """Latest quarter end (31 Mar / 30 Jun / 30 Sep / 31 Dec) that is already over."""
    for y, m, d in ((today.year, 12, 31), (today.year, 9, 30), (today.year, 6, 30), (today.year, 3, 31),
                    (today.year - 1, 12, 31)):
        q = dt.date(y, m, d)
        if q < today:
            return q


def new_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    s.get("https://www.nseindia.com/", timeout=30)
    return s


def get(s, url, tries=3):
    for i in range(tries):
        try:
            r = s.get(url, timeout=40)
            if r.status_code == 200:
                return r
            if r.status_code in (401, 403):
                time.sleep(3)
                s.get("https://www.nseindia.com/", timeout=30)  # cookie refresh
        except requests.RequestException:
            pass
        time.sleep(2 + i * 2)
    return None


def parse_date(v):
    for f in ("%d-%b-%Y", "%d-%b-%Y %H:%M:%S", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(str(v).strip(), f).date()
        except ValueError:
            pass
    return None


def fpi_count_from_xbrl(xml, sym):
    """Sum 'number of shareholders' of the FPI contexts (Category I + II). Returns int or None."""
    ctx = {}
    for m in re.finditer(r'<(?:\w+:)?context\b[^>]*\bid="([^"]+)"[^>]*>(.*?)</(?:\w+:)?context>', xml, re.S):
        ctx[m.group(1)] = m.group(2)
    found = {}
    for m in re.finditer(r'<(?:\w+:)?(NumberOfShareholders?|NumberOfShareHolders?)\b[^>]*contextRef="([^"]+)"[^>]*>\s*([\d,\.]+)\s*<', xml):
        cid, val = m.group(2), m.group(3).replace(",", "")
        body = ctx.get(cid, "") + " " + cid
        low = body.lower()
        if "foreignportfolio" in low or "foreign portfolio" in low:
            # sub-total contexts (Category I / II) ko jodo; "Total"/"Others" jaisa kuch ho to skip
            if "categoryi" in low.replace(" ", "") or "categoryii" in low.replace(" ", ""):
                try:
                    found[cid] = int(float(val))
                except ValueError:
                    pass
    if not found:
        with open(DEBUG, "a") as f:
            f.write(f"{sym}: FPI context nahi mila. contexts={len(ctx)} sample={list(ctx)[:6]}\n")
        return None
    return sum(found.values())


def fetch_symbol(s, sym):
    r = get(s, LIST_URL.format(sym=sym))
    if not r:
        return None
    try:
        items = r.json()
    except ValueError:
        return None
    if isinstance(items, dict):
        items = items.get("data") or items.get("rows") or []
    items = [i for i in items if i.get("xbrl") or i.get("attachment")]
    for i in items:
        i["_d"] = parse_date(i.get("date") or i.get("asOnDate") or "")
    items = sorted([i for i in items if i["_d"]], key=lambda i: i["_d"], reverse=True)
    res = []
    for it in items[:2]:                       # latest + previous quarter
        url = it.get("xbrl") or it.get("attachment")
        if not str(url).lower().endswith(".xml") and "xbrl" not in str(url).lower():
            continue
        x = get(s, url)
        time.sleep(0.6)
        n = fpi_count_from_xbrl(x.text, sym) if x else None
        if n is not None:
            res.append((n, it["_d"].isoformat()))
    if not res:
        return None
    cur = res[0]
    prev = res[1][0] if len(res) > 1 else None
    return [cur[0], prev, cur[1]]


def main():
    data = {"updated": "", "stocks": {}}
    if os.path.exists(OUT):
        with open(OUT) as f:
            data = json.load(f)
    st = data.setdefault("stocks", {})
    if os.environ.get("FII_SYMBOLS"):
        syms = [x.strip().upper() for x in os.environ["FII_SYMBOLS"].split(",") if x.strip()]
    else:
        with open(SECTORS, newline="", encoding="utf-8-sig") as f:
            syms = [r[0].strip().upper() for r in csv.reader(f) if r and r[0].strip()][1:]
    today = dt.date.today()
    qe = quarter_end(today).isoformat()
    todo = []
    for sym in syms:
        e = st.get(sym)
        if e is None:
            todo.append((0, sym))                                   # kabhi nahi liya
        elif e[2] < qe and (today - dt.date.fromisoformat(e[3])).days >= RECHECK_DAYS:
            todo.append((1, sym))                                   # naya quarter aa sakta hai
    todo.sort()
    todo = [s for _, s in todo][:MAX_PER_RUN]
    print(f"{len(todo)} stocks is run me (quarter end {qe})")
    if not todo:
        return
    s = new_session()
    ok = 0
    for i, sym in enumerate(todo, 1):
        try:
            r = fetch_symbol(s, sym)
        except Exception as e:  # noqa: BLE001
            print("skip", sym, e)
            r = None
        if r:
            st[sym] = r + [today.isoformat()]
            ok += 1
        else:
            old = st.get(sym)
            st[sym] = (old[:3] if old else [None, None, "0000-00-00"]) + [today.isoformat()]  # retry kuch din baad
        if i % 25 == 0:
            print(f"{i}/{len(todo)}  ok={ok}")
            data["updated"] = today.isoformat()
            with open(OUT, "w") as f:
                json.dump(data, f, separators=(",", ":"))
        time.sleep(0.8)
    data["updated"] = today.isoformat()
    with open(OUT, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    print(f"done ok={ok}/{len(todo)}")
    if ok == 0:
        sys.exit(1)   # workflow warning: NSE format/blocking check karo (fii_debug.txt)


if __name__ == "__main__":
    main()
