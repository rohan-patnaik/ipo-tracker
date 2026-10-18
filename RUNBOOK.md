# IPO tracker: scheduled run (any machine, nothing kept)

- **Live page:** https://rohan-patnaik.github.io/ipo-tracker/ (repo `rohan-patnaik/ipo-tracker`, deployed by GitHub Actions).
- **The GitHub job** refreshes numbers every 30 minutes in market hours. It locks each IPO's call at 2 pm IST on its last day (`data/results.json`) and deploys.
- **This run** only reads Anant Ladha (InvestAajForKal) and records his latest view per IPO in `data/notes.json`. YouTube blocks transcripts from cloud IPs, so this runs on a home machine: `rohan-omarchy` preferred, the Mac as a stand-in.
- **Owner's rule:** nothing is kept on the machine. Work in a temporary folder, delete it at the end, even if something failed. Transcripts are never stored anywhere.
- **Settings** (`config.json`): one PAN, ₹3,00,000 max blocked at once, listing gains only, GMP gate 15%.
- **Schedule:** weekdays at 11:15 and 13:30 IST, so Anant's latest view is in before the 2 pm lock.

## Steps

```bash
W=$(mktemp -d /tmp/ipo-run.XXXXXX)
gh repo clone rohan-patnaik/ipo-tracker "$W/repo" -- --depth 30 --quiet
cd "$W/repo"
git config user.name "Rohan Patnaik"; git config user.email "rohanpatnaik1997@gmail.com"
IPO_TRANSCRIPT_DIR="$W" python3 fetch.py     # numbers + every unread Anant video -> $W/ipo-transcripts/
```

1. Read `raw/digest.md`. For every new video marked **MENTIONS IPO**, read its transcript.
   - The transcripts are Hindi auto-captions. Names and numbers can be garbled, so cross-check with Chittorgarh.
   - Skim the "no IPO mention" ones only if the title suggests markets or IPOs.
   - Telegram lines carry his GMP and subscription posts. GMP posts are picked up automatically.
2. Update `data/notes.json` with his **latest** view per IPO slug (a later video or post overrides an earlier one):
   - `anant`: `A` / `B` / `C`. Use `A?` if clearly positive without a letter, `—` if not covered.
   - `anant_said`: short bullets of positives, negatives and what to watch.
   - `anant_updated`: date of his latest view. `video`: link with `&t=` from the chapter timestamps.
   - `risk`:
     - Low: GMP ≥ 25% and steady, profitable, strong demand.
     - Medium: GMP 15–25% or volatile, or one red flag.
     - High: GMP < 15% or falling, loss-making, weak QIB, or SME.
   - Add `risk_why`.
   - If his latest view raises a serious red flag that the numbers don't show (weak anchor book, governance), add `"override": {"verdict": "SKIP", "reason": "..."}`. Overrides can only force SKIP.
   - SME IPOs are shown only if he rates them A.
   - If the owner reported applying or allotment, set `"you": {"applied": true, "allotted": true|false|null, "gain_inr": n|null}`.
   - Refresh `headline` (one or two plain sentences about the next last day) and `updated_at`.
   - **Do not write calls.** Apply/Skip is computed by `rules.py` on the last day and locked at 2 pm.
3. Publish and clean up:

```bash
./publish.sh                 # self-check, commit notes + read-videos list, push (the job redeploys in ~1 min)
cd / && rm -rf "$W"          # always: transcripts and the clone are deleted
```

4. Post a short message in the thread:
   - what changed in Anant's views;
   - any IPO whose last day is today or tomorrow, with its current call or lean and the amount (1 lot);
   - the page link;
   - any failures (for example, YouTube blocking transcripts; they're retried next run).

## Housekeeping

- Add NSE holidays to `config.json` → `holidays` when a new month starts.
- `data/results.json` is written only by the GitHub job.
- `tools/replay.py` re-tests the rule on past IPOs (`tools/gmp_history.py` downloads their GMP history first).
- If the job fails, check `gh run list -R rohan-patnaik/ipo-tracker`. A source changing its HTML is the usual cause.
