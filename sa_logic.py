"""Regime / setup / note rules for the Market Situational Awareness monitor.

Input rows (oldest first): dict with date, MR20, U4, D4, W20, universe.
Rules come from "Market Situational Awareness prompt.docx". The Chop rule was
calibrated against the SA_Market_Monitor.xlsx sheet: 3+ direction flips across
the last 5 MR20 moves (99.25% regime match with the sheet's 2016-2026 history).
"""

SETUP = {
    "Oversold": "Bounce / dip setups",
    "Falling (3+ days)": "Reversal setups (naye long ruk ke)",
    "Overextended": "Parabolic short / caution, fresh breakout nahi",
    "Overbought": "Caution, breakout chhota size, hold wale chalne do",
    "Chop": "SIIPS + Fades (breakout avoid)",
    "Neutral_hi": "Continuation + Breakout",
    "Neutral_lo": "Wait: market kamzor, chhota size; MR20<20 pe bounce dekho",
}
FRESH_SWING = "Fresh swing, bottom bounce / long"


def _sgn(x):
    return 1 if x > 0 else (-1 if x < 0 else 0)


def enrich(rows):
    """Return rows with change, streaks, regime, setup and note added."""
    out = []
    up = down = 0
    prev_regime = None
    for i, r in enumerate(rows):
        mr = r["MR20"]
        change = round(mr - rows[i - 1]["MR20"], 1) if i else 0.0
        if i and change > 0:
            up, down = up + 1, 0
        elif i and change < 0:
            up, down = 0, down + 1
        else:
            up = down = 0

        # chop: 3+ direction flips across the last 5 MR20 moves
        flips = 0
        if i >= 5:
            moves = [rows[k]["MR20"] - rows[k - 1]["MR20"] for k in range(i - 4, i + 1)]
            d = [_sgn(x) for x in moves]
            flips = sum(1 for a, b in zip(d, d[1:]) if a != b)

        if mr < 20:
            regime = "Oversold"
        elif down >= 3:
            regime = "Falling (3+ days)"
        elif mr >= 80 and r["W20"] >= 20:
            regime = "Overextended"
        elif mr >= 80:
            regime = "Overbought"
        elif flips >= 3:
            regime = "Chop"
        else:
            regime = "Neutral"

        if regime == "Neutral":
            setup = SETUP["Neutral_hi"] if mr >= 40 else SETUP["Neutral_lo"]
        else:
            setup = SETUP[regime]
        if r["U4"] >= 250:
            setup = FRESH_SWING

        notes = []
        if up >= 4:
            notes.append(f"MR20 {up} din se badh raha: fresh entry me caution")
        if r["W20"] >= 20:
            notes.append("W20 high: market stretched")
        if r["D4"] >= 60:
            notes.append(f"D4 {r['D4']}: sharp selloff")
        if r["U4"] >= 100:
            notes.append(f"U4 {r['U4']}: strong breadth")
        if i and prev_regime and regime != prev_regime:
            notes.append(f"Regime badla: {prev_regime} se {regime}")
        elif i and rows[i - 1].get("_up", 0) >= 3 and up == 0 and change < 0:
            notes.append("MR20 ki badhne ki streak tooti")
        prev_regime = regime

        row = dict(r)
        row.update(
            {
                "MR20_change": change,
                "up_streak": up,
                "down_streak": down,
                "regime": regime,
                "setup": setup,
                "note": " | ".join(notes),
            }
        )
        rows[i]["_up"] = up
        out.append(row)
    for r in rows:
        r.pop("_up", None)
    return out
