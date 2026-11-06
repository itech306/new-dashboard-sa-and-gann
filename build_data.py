"""One-time: turn the Daily Monitor sheet into data.json (oldest first).

Usage: python build_data.py SA_Market_Monitor.xlsx
"""
import json
import sys

import openpyxl

from sa_logic import enrich

wb = openpyxl.load_workbook(sys.argv[1], data_only=True)
ws = wb["Daily Monitor"]
rows = list(ws.iter_rows(values_only=True))
hdr = rows[0]
raw = [dict(zip(hdr, r)) for r in rows[1:] if r[0]]
raw.sort(key=lambda d: str(d["date"]))

base = [
    {
        "date": str(d["date"])[:10],
        "MR20": d["MR20"],
        "U4": d["U4"],
        "D4": d["D4"],
        "W20": d["W20"],
        "universe": d["stocks_in_universe"],
    }
    for d in raw
]
full = enrich(base)

# compare with the sheet
mism = sum(1 for a, b in zip(full, raw) if a["regime"] != b["regime"])
print(f"{len(full)} rows, regime mismatch vs sheet: {mism}")

with open("data.json", "w") as f:
    json.dump({"updated": full[-1]["date"], "rows": full}, f, separators=(",", ":"))
