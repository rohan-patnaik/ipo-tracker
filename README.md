# IPO tracker

A personal page that says which Indian IPOs to apply for, when, and with how much, for listing gains:
https://rohan-patnaik.github.io/ipo-tracker/

- **Numbers** come from Chittorgarh (dates, price, subscription, applications, listing-day prices) and from InvestorGain and IPOWatch (GMP). A GitHub job refreshes them every 30 minutes in market hours.
- **Calls** follow Anant Ladha's (InvestAajForKal) A/B/C rankings and a GMP gate. A scheduled assistant reads his video transcripts and Telegram posts on a Mac and writes `data/notes.json`.
- **Track record**: `data/results.json` freezes every call at close and adds the listing-day result. `data/backfill.json` holds his earlier calls.
- **Phone alerts**: subscribe to `ipo.ics` from the page.

Not investment advice.
