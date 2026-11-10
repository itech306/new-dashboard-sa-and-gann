# SA Market Monitor (free, EOD)

Roz shaam ko NSE bhavcopy se MR20, U4, D4, W20 nikalta hai, regime/setup/note lagata hai, aur website par dikhata hai. Sab free: GitHub Actions (data) + GitHub Pages (site).

## Files

- `index.html` : website (data.json padhti hai)
- `data.json` : tumhari sheet ka poora history (2016 se 9 Oct 2026), roz naya din judta hai
- `screeners.py`, `screeners.html`, `sector_map.csv` : Sourav Strong Sector and Group Mover Finder (neeche dekho)
- `gann.py`, `gann.html` : Gann Price-to-Time aur 3-6-9 Cluster screener (neeche dekho)
- `update.py` : bhavcopy download + calculation
- `sa_logic.py` : regime / setup / note ke rules (Word prompt wale)
- `build_data.py` : sheet se data.json dobara banane ke liye (zaroorat nahi padegi)
- `.github/workflows/update.yml` : roz 7 PM IST par update.py chalata hai

## Setup (10 minute)

1. GitHub par naya **public** repo banao (e.g. `sa-monitor`) aur ye saari files upload karo (`.github` folder samet).
2. Repo me **Settings > Pages > Build and deployment**: Source = "Deploy from a branch", Branch = `main`, folder = `/ (root)`. Save.
3. **Actions** tab me "Daily EOD update" kholo aur **Run workflow** dabao. Pehli baar ye 12 Oct se aaj tak ka gap bharega aur EMA ke liye ~150 din ki history download karega (kuch minute lagenge).
4. Site `https://<tumhara-username>.github.io/sa-monitor/` par khulegi. Uske baad roz apne aap update hogi.

## Pehle din ye zaroor check karo

- **Chartink se milao.** Gap bharne ke baad 12 Oct se 30 Oct ke MR20/U4/D4/W20 apne Chartink ke numbers se compare karo. Agar thoda fark ho to `update.py` ke upar `AVG_TURNOVER_CR`, `MIN_PRICE`, `U4_PCT` aur U4/D4 ka volume condition tumhare scan jaisa kar do.
- Bhavcopy ka URL/columns NSE ne pehle badle hain. Agar Actions me "unexpected columns" ya "No new trading days" aaye to log dekho aur URL wali `URLS` list update karo.
- Raw bhavcopy unadjusted hota hai. Script split/bonus NSE ke `PrvsClsgPric` column se adjust karti hai. Ye assumption hai ki NSE ex-date par ye column adjust karta hai; kisi split wale din ek baar manually check kar lena.
- Regime logic tumhari sheet ke 2661 me se 2637 din se match karta hai. Chop ka rule sheet se calibrate hua hai: pichle 5 MR20 moves me 3+ baar direction badli.
- Agar repo kai hafte inactive rahe to GitHub scheduled workflow band kar sakta hai. Actions tab se dobara enable kar do.


## Sourav Strong Sector and Group Mover Finder (screeners.html)

Daily 4%, 20%/13% in 5 days, 50% in 14 days, 50% in 2 months aur weekly 13%/20% ke hits, sector/industry/subgroup ke group movers ke saath. Data `screener_data.json` me hai, jo `update.py` roz banata hai.

- **Daily** sirf 4% ke liye hai (cool-off nahi). Baaki screeners **Weekly** (pichle 7 din) aur **Monthly** (jaise 4 Oct se 4 Nov) window me dikhte hain.
- **Cool-off**: 5d = 5 trading days, 14d = 14, 2 month = 40, weekly = 1 completed week. Jis din stock pehli baar dikhta hai wahi se cool-off shuru hota hai.
- **Weekly screeners** sirf poore hue hafte (Friday) par check hote hain. Chalta hua hafta count nahi hota.
- **Naya IPO**: `sector_map.csv` me ek line jodein: `SYMBOL,Industry,Subgroup`. GitHub par file edit karke save karte hi workflow chalta hai aur `screener_data.json` naya ban jaata hai. Jo stock file me nahi hai wo page ke neeche "Sector file me nahi mile" me dikhta hai (CSV lines copy button ke saath).
- History ab ~3 saal (~750 trading din) rakhi jaati hai (weekly volume SMA(50) + Gann swing anchors ke liye). Pehla run lamba lagega (30-40 minute).
- Turnover (close x volume) NSE ke traded value column se liya hai. Chartink se ek baar numbers milao, fark ho to `screeners.py` ke upar ke constants badal do.

### IPO (last 1 year)

- Listing date NSE ki `EQUITY_L.csv` se roz `listing_dates.csv` me aati hai (NSE band ho to purani file chalti hai). Chaho to `sector_map.csv` me optional `Listing Date` column bhi de sakte ho, wo sabse upar maana jaayega.
- Jo stock last 365 din me listed hai wo page par "IPO" badge ke saath dikhta hai, aur apni normal Industry/Subgroup me bhi ginta hai. Har bar me IPO ka hissa alag rang me aur "(3 IPO)" likha aata hai.
- "Sirf IPO (last 1 year)" button se tiles, charts aur table sirf IPO stocks tak limit ho jaate hain.
- Naye IPO ke paas 50 din ka data nahi hota, isliye 4% screener me wo shuru ke ~50 din nahi aate (Chartink me bhi aisa hi hota hai). Chaho to `screeners.py` me `IPO_RELAX_SMA = True` kar do.

### Sector file kaise update karein

Naya IPO aaye to page ke neeche "Sector file me nahi mile" panel me dikhega. "CSV lines copy" dabao, GitHub par `sector_map.csv` kholo, pencil icon se lines neeche paste karo, industry aur subgroup bharo (spelling purani file jaisi), Commit karo. Workflow apne aap chal ke page update kar dega.

### Repo ka size

`history.csv.gz` ab repo me commit nahi hoti, GitHub Actions cache me rehti hai (roz chalne se cache zinda rehta hai). Kabhi cache hat jaye to agla run ~750 din ka data dobara download karega (30-40 min), kuch kharab nahi hota.


## Gann Screener (gann.html)

Pine script "price and time by sourav karhana" ke Module 1 (Price-to-Time) aur Module 2 (3-6-9 Time Cluster) ka screener. Data `gann_data.json` me hai, jo `update.py` roz banata hai.

- **Universe:** Weekly ya Monthly window ke **top 5 Industry + top 5 Subgroup** (screeners: 20% in 5 Days, 13% in 5 Days, 13% in a Week ke hits se) ke saare stocks. Liquidity: `SMA(close x volume, 20) > 3 crore` aur `close > 20`. "SCREENER" badge un stocks par jinhone khud screener hit diya.
- **Anchors:** har stock ka latest confirmed swing high (H) aur swing low (L), Pine ke `ta.pivothigh/pivotlow` jaisa. Strength 20 / 30 / 40 bars each side, page par select hota hai.
- **Price-to-Time:** aaj ka bar = anchor bar + round(base x i), i = 1..9.
- **3-6-9 Cluster:** aaj ka bar (ya Calendar-days mode me aaj ki date) = anchor + 30, 60, 90 ... 720. H aur L dono ki line ek din mile to Cluster. "1+ line" se sirf ek line wale bhi dikhte hain.
- Sirf **aaj ka din** dekha jaata hai (na past, na future). Prices split/bonus adjusted.
- `gann.py` ke upar constants: `STRENGTHS`, `CYCLES`, `GROUP_SCREENERS`, `TOP_N`, `LIQ_MIN`, `ONLY_SCREENER_HITS` (True karne par top groups ke sirf screener-hit wale stocks aayenge).
## Shravya Market Scanz UI

`index.html` अब Shravya Market Scanz का unified dashboard है। यह `data.json` से Market Monitor live data पढ़ता है और उपलब्ध होने पर `screener_data.json` का इस्तेमाल करता है। `screeners.html` और `gann.html` standalone pages के रूप में भी रखे गए हैं।


- `index.html` (aur uski copy `ShravyaMarketScanz.html`) ab `data.json`, `screener_data.json` aur `gann_data.json` teeno real padhti hai. Jo file repo me nahi hoti (workflow ek baar chale bina) uske liye "Demo" sample dikhta hai.

## Stock chart on hover (charts.py)

- Kisi bhi stock symbol par mouse le jao: 126 din ka candle chart aata hai (Swing Master v2 colours/markers). Symbol par click abhi bhi TradingView/Chartink kholta hai.
- Hover par chart card aata hai. Symbol ke saath wala ⤢ button ek click me seedha full-screen viewer kholta hai (Prev/Next ya ArrowLeft/ArrowRight se list me aage-peeche, Esc / X se band, ⛶ se browser fullscreen).
- Chart par neela vertical band = us din stock us screener me aaya tha (Gann/Gap Up pages par saare screeners). Halka laal band = 50 SMA downside extension.
- `charts.py` roz `gann.run()` se `gann_history/chart_data.json` banata hai (sirf screener hits + Gann + Gap Up stocks). File na ho to baaki site pehle jaisi chalti hai aur chart "Chart not available" dikhata hai.
- Workflow me koi badlav nahi chahiye (`git add -A gann_history` is file ko bhi commit kar deta hai).


## Charts (interactive, TradingView jaisa)

Files: `chart.html` (chart), `index.html` / `ShravyaMarketScanz.html` (dashboard: screener / strong groups me stock par hover, pin ya expand dabao to yahi chart khulta hai), `charts.py` (workflow me chart data banata hai).

1. Zip ki files repo me replace karo (`chart.html`, `index.html`, `ShravyaMarketScanz.html`, `charts.py`) aur push karo. `chart.html` `index.html` ke bagal me root me rahe.
2. Actions tab me "Update" workflow ek baar Run karo. Wo `gann_history/chart_data.json` aur `gann_history/h/*.json` (volume ke saath; ~750 trading days bhavcopy se + usse purani history free Yahoo se, listing tak) banata hai. Roz apne aap update hota hai.
3. Site kholo, kisi stock par hover karo. Chart me: scroll = zoom, drag = peeche/aage, EMA 10/20/50/100/200, Vol, Flags, A (auto-fit), L (log), Dark/Light.

Chart sirf un stocks ka banta hai jo us din screeners / Gann / Gap Up lists me hain. Site ko GitHub Pages / server se kholo (file:// se fetch nahi chalta).

### Purani (750 din se pehle ki) history
`charts.py` har stock ke liye Yahoo Finance (free, `yfinance`) se poori purani history leke 750-din wali series ke pehle jod deta hai (price split-adjusted, continuity ke liye scale). Yahoo na chale / rate-limit kare to chart sirf ~750 din ka banta hai, workflow fail nahi hota. Band karna ho to workflow me env `FULL_HISTORY=0` do.


## Max Return column (Price-to-Time, 3-6-9, Gap Up)

- Date picker me koi **purani date** (jaise 4 Nov) chuno to in teeno tables me Avg turnover ke bagal me **Max Return** aata hai: us din ke close se uske baad (aaj tak) ka sabse ooncha price kitna gaya.
- Neeche chhoti line: kis din peak bana aur **now** = aaj ka close us din ke close se kitna upar/neeche.
- Upar **Max by High** (intraday high, default) / **Max by Close** (sirf closing) toggle hai. Header par click karke sort bhi kar sakte ho.
- Latest date par column "—" dikhata hai (abhi koi "baad ka din" nahi hai).
- Data `gann_history/px.json` se aata hai (gann.py roz banata hai, split/bonus adjusted, last 30 trading days). Workflow me koi badlav nahi chahiye (`git add -A gann_history` ise bhi commit karta hai).
