# Prompt (is project me aage kaam karwane ke liye)

Project: "sa-monitor" (Shravya Market Scanz), static GitHub Pages site (single-file index.html, ShravyaMarketScanz.html is an identical copy) fed by a daily GitHub Actions job (update.py, screeners.py, gann.py, charts.py).
Read ALL files first (update.py, screeners.py, gann.py, charts.py, index.html, .github/workflows/update.yml, README.md) before changing anything. Do not break: date picker, "Top 5 groups / All stocks" toggle, Gap Up, Gann snapshots in gann_history/, hover/pin/expand chart, blue screener-hit bands.

How the chart feature works
- charts.py (called at the end of gann.run) computes Swing Master v2 flags in pandas and writes gann_history/chart_data.json (last 126 bars, prices in paise, delta-encoded; format is documented at the top of charts.py). gann.py's pruning loop must never delete chart_data.json.
- index.html: tv(sym) renders the symbol link (class "sl") plus an "i" button (class "chi"). The JS block "Stock chart on hover / pin / expand" fetches chart_data.json lazily, draws the SVG (chartSVG), shows the hover card (#hc, pointer-events:none), the pinned card (expand button only when pinned) and the full-screen overlay (#xo) that steps through the LIST array. xRe() is called wherever LIST is re-assigned and closes card/overlay.
- Blue band = day the stock hit the current screener (D.hits); light red band = 50 SMA downside extension ((close - SMA50)/ATR14 <= -3).

Rules for every change
- Keep index.html and ShravyaMarketScanz.html identical, no external libraries, works in light and dark theme (chart stays white), keep helper names (tv(), toast, segBtns, LIST/LN, ASOF).
- The Pine script wins over the written Swing Master rules if both exist.
- Test: run gann.py on synthetic history, test the page in a real browser (hover, click-through to TradingView, i button pin, expand, Prev/Next, Esc order, mobile 390px, light/dark), and give back only the changed files with a short Hinglish upload guide.

Next change I want:
<yahan likho>
