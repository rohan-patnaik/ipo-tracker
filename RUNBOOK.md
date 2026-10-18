# IPO tracker: scheduled run (Mac)

- **Live page:** https://rohan-patnaik.github.io/ipo-tracker/ (repo `rohan-patnaik/ipo-tracker`, deployed by GitHub Actions).
- **The GitHub job** (`.github/workflows/refresh.yml`) refreshes numbers every 30 minutes in market hours, updates `data/results.json` and deploys. It also runs on every push of calls.
- **This Mac run** only reads Anant (YouTube transcripts are blocked from cloud IPs) and edits the calls in `data/notes.json`.
- **Owner's settings** (`config.json`): one PAN, ₹3,00,000 max blocked at once, listing gains only, GMP gate 15%.
- **Schedule:** weekdays at 11:15 and 14:00 IST. The Mac is on about 11:00–18:00.

## Every run

1. `git pull --rebase --quiet`, then `python3 fetch.py`. It writes `data/auto.json` and `raw/digest.md`, which includes three GMP sources, application counts and registrar.
   If YouTube blocks transcripts, note the missing transcript and retry next run. Don't loop on it.
2. Read `raw/digest.md`.
   - For each **NEW** IPO video, read `raw/transcripts/<id>.txt` (Hindi auto-captions; cross-check numbers with Chittorgarh).
   - Pull Anant's A/B/C call, positives, negatives and what to watch. Chapter timestamps in the description give `&t=` links.
   - Telegram lines carry his own GMP and subscription posts. The page picks up GMP posts automatically.
3. Update `data/notes.json`, one entry per IPO slug:
   - `anant`: `A` / `B` / `C`. Use `A?` if he's clearly positive but gave no letter, `—` if not covered.
   - `verdict`:
     - `APPLY`: A (or `A?`), GMP ≥ gate, demand OK.
     - `CONDITIONAL`: passes rating and GMP, but one check is open. Write the exact condition.
     - `WAIT`: not open yet, or not covered yet.
     - `SKIP`: B or C, or GMP < gate.
   - Leave verdicts as they are after an IPO closes. `results.py` freezes them into the track record.
   - On the **14:00 run on a closing day**, resolve every `CONDITIONAL` to `APPLY` or `SKIP` with the live numbers.
   - `risk`:
     - Low: GMP ≥ 25% and steady, profitable, strong demand.
     - Medium: GMP 15–25% or volatile, or one red flag.
     - High: GMP < 15% or falling, loss-making, weak QIB, or SME.
   - `lots`: 1 by default; 0 for SKIP/WAIT. Peak money blocked must stay ≤ `capital_inr`.
   - SME IPOs only if Anant rates them A.
   - When the owner says whether they applied or got shares, set `"you": {"applied": true, "allotted": true|false|null, "gain_inr": n|null}`.
   - Refresh `headline` (one or two plain sentences about the next deadline) and `updated_at`.
4. `./publish.sh`. It runs the self-check (`render.py --strict`) and refuses to push a call that breaks the rules. Fix the note, or add an `"override"` reason if a rule break is intended. On success it commits and pushes, and the GitHub job rebuilds the page in about a minute.
5. Post a short message in the thread:
   - what changed (new Anant call, verdict flips, GMP crossing the gate, sources disagreeing);
   - today's to-dos with amounts;
   - the page link;
   - any failures.
   If nothing changed, say so in one line.

## Housekeeping

- Add NSE holidays to `config.json` → `holidays` when a new month starts.
- `data/results.json` is written only by the GitHub job. Don't commit it from the Mac (`publish.sh` discards local changes to it).
- `data/backfill.json` holds Anant's calls from his Sep–Oct 2026 ranking videos, with listing results. Add older ones the same way if wanted.
- If the job starts failing, check `gh run list -R rohan-patnaik/ipo-tracker`. A source changing its HTML is the usual cause.
