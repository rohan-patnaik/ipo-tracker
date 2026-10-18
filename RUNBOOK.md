# IPO tracker: scheduled runs (master + worker)

- **Live page:** https://rohan-patnaik.github.io/ipo-tracker/ (repo `rohan-patnaik/ipo-tracker`).
- **GitHub job:** refreshes numbers every 30 minutes in market hours, locks each IPO's call at 2 pm IST on its last day (`data/results.json`), and deploys.
- **Master (Claude):** the Mac thread `c823dbae-d274-40ae-a334-ff07341f20eb`, environment `99179f23-e33b-491f-bddd-3f2107892d53`. Owns the schedules (weekdays 11:15 and 13:30 IST), reads Anant Ladha's transcripts, writes his latest view per IPO, and answers the owner's questions.
- **Worker (Codex):** the thread "IPO tracker runner" `mcp:aca6731e-856b-496d-b25d-3fba5d3e8542` on `rohan-omarchy`, environment `bce78c30-3a78-4b50-80e8-89b084740a43`. Mechanical commands only. YouTube transcripts must come from this home connection; cloud IPs are blocked.
- **Owner's rules:** nothing is kept on any machine (transcripts and clones live in a temporary folder on the PC and are deleted after each run). One PAN, ₹3,00,000 cap, listing gains only, GMP gate 15% (`config.json`).

## Master run (each scheduled slot)

1. Send the worker `IPO-WORKER FETCH` with `connected_thread_send`, using a new requestId per run, e.g. `ipo-fetch-YYYYMMDD-HHMM`. Poll `connected_thread_read` every ~20 s until the run completes; give up after 15 minutes.
   - The reply has `WORKSPACE=…`, `FETCH_EXIT=…` and `TRANSCRIPTS=…`.
   - If the PC is unreachable, post that here and stop. The GitHub job still locks calls with Anant's last saved grade.
2. Read from the PC with `connected_environment_rpc` → `projects.readFile`, using `{"cwd": "<WORKSPACE>", "relativePath": "repo/raw/digest.md"}`, then each `ipo-transcripts/<id>.txt` marked **MENTIONS IPO**. Also read `repo/data/notes.json`.
   - The transcripts are Hindi auto-captions. Names and numbers can be garbled, so cross-check with the digest's Chittorgarh numbers.
   - Telegram lines in the digest carry his GMP and subscription posts.
3. Build the new `notes.json`, with his **latest** view per IPO slug:
   - `anant`: `A` / `B` / `C`. Use `A?` if clearly positive without a letter, `—` if not covered.
   - `anant_said`: short bullets.
   - `anant_updated`: date of his latest view. `video`: link with `&t=` from the chapter timestamps.
   - `risk` (Low / Medium / High, with the rubric in the page footer) and `risk_why`.
   - `"override": {"verdict": "SKIP", "reason": "…"}` only for a serious red flag he raises that the numbers don't show.
   - `"you": {…}` when the owner reported applying or allotment.
   - Refresh `headline` and `updated_at`.
   - Never write Apply/Skip calls; `rules.py` computes them on the last day.
   - Keep existing entries for closed IPOs unchanged.
4. Send the worker `IPO-WORKER PUBLISH <WORKSPACE>` followed by the full JSON in a fenced block. Wait for `PUBLISH=` and `CLEANED=yes`.
   - If publish fails the self-check (`render.py --strict`), fix the JSON and resend.
   - If anything goes wrong, send `IPO-WORKER CLEANUP <WORKSPACE>`.
5. Post a short summary in the master thread:
   - changes in Anant's views;
   - every IPO whose last day is today or tomorrow, with its current call or lean and the 1-lot amount;
   - the page link;
   - failures.
   The 13:30 run leads with today's last-day IPOs; the final call locks at 2 pm.

If there are no new videos and no relevant Telegram posts, skip step 4 (send `IPO-WORKER CLEANUP <WORKSPACE>`) and post one line.

## Housekeeping

- Add NSE holidays to `config.json` → `holidays` when a new month starts. Make the edit in a worker workspace before PUBLISH.
- `data/results.json` is written only by the GitHub job.
- `tools/replay.py` re-tests the rule on past IPOs.
- The Mac's T3 Connect access to `rohan-omarchy` expires on 2026-11-12. Renew it before then.
- If the job fails, check `gh run list -R rohan-patnaik/ipo-tracker`.
