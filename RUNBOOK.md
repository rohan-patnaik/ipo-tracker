# IPO tracker: scheduled run

Live page: https://rohan-patnaik.github.io/ipo-tracker/ (from `site/index.html`, pushed to the portfolio repo's `ipo-tracker/` folder only).

Owner's settings (`config.json`): one PAN, ₹3,00,000 max blocked at once, listing gains only, GMP gate 15%.
Mac is on about 11:00–18:00 IST on weekdays, so runs happen at 11:15 and 14:00.

## Every run

1. `cd` here and run `python3 fetch.py`. It writes `data/auto.json` (dates, price, lot, subscription, GMP) and `raw/digest.md`.
   If YouTube blocks transcripts, the run still works; note the missing transcript and retry next run. Don't loop on it.
2. Read `raw/digest.md`.
   - For each **NEW** IPO video, read `raw/transcripts/<id>.txt` (Hindi auto-captions; numbers can be garbled, so cross-check against Chittorgarh).
   - Pull Anant's A/B/C call, positives, negatives and what he says to watch. Chapter timestamps in the description give `&t=` links.
   - Scan the Telegram lines for Anant's own GMP or subscription notes on tracked IPOs.
3. Update `data/notes.json`. Keep the existing shape, one entry per IPO slug:
   - `anant`: `A` / `B` / `C`. Use `A?` if he's clearly positive but gave no letter, `—` if not covered.
   - `verdict`:
     - `APPLY`: Anant A (or `A?`), GMP ≥ gate, demand OK.
     - `CONDITIONAL`: passes rating and GMP, but one check is open (usually QIB on the last day). Write the exact condition.
     - `WAIT`: not open yet, or not covered yet.
     - `SKIP`: B or C, or GMP < gate.
     - `CLOSED`: after the last day.
   - On the **14:00 run on a closing day**, resolve every `CONDITIONAL` to `APPLY` or `SKIP` using the live numbers.
   - `risk` (chance of losing money on listing day):
     - Low: GMP ≥ 25% and steady, profitable, strong demand.
     - Medium: GMP 15–25% or volatile, or one red flag (100% OFS, rich P/E, very large issue).
     - High: GMP < 15% or falling, loss-making, weak QIB, or SME.
   - `lots`: 1 by default; 0 for SKIP/WAIT/CLOSED. Keep the total blocked at once ≤ `capital_inr`. The page shows the peak.
   - SME IPOs appear only if Anant rates them A. Otherwise leave them out of `notes.json`.
   - Refresh `headline` (one or two plain sentences about the next deadline) and `updated_at`.
4. `python3 render.py && ./publish.sh`.
5. Post a short message in the thread:
   - what changed since last run (new Anant call, verdict flips, GMP crossing the gate);
   - today's to-dos with amounts;
   - the page link;
   - any source failures.
   If nothing changed, say so in one line.

## Housekeeping

- Add NSE holidays to `config.json` → `holidays` when a new month starts (check NSE's holiday list).
- After an IPO lists, it drops off automatically within ~6 days.
- To change the gate or capital, edit `config.json`, then re-render.
