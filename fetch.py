"""Collect free IPO data: Chittorgarh (dates, price, subscription), InvestorGain (GMP),
Anant Ladha's YouTube (RSS + Hindi transcripts) and his public Telegram channel.

Writes data/auto.json (machine-parsed numbers) and raw/digest.md (for the judgement pass).
Stdlib only; transcripts go through `uvx youtube-transcript-api`.
"""
import datetime as dt
import html
import json
import re
import subprocess
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA, RAW = ROOT / "data", ROOT / "raw"
CHANNEL_ID = "UCWHCXSKASuSzao_pplQ7SPw"
TELEGRAM = "https://t.me/s/anantladhaofficialid"
CG = "https://www.chittorgarh.com"
CALENDARS = {"mainboard": f"{CG}/calendar/ipo-calendar/1/", "sme": f"{CG}/calendar/sme-ipo-calendar/2/"}
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128 Safari/537.36"}
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
TODAY = dt.datetime.now(IST).date()
WINDOW_BACK, WINDOW_AHEAD = 6, 21  # days around today an IPO must touch to be tracked


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "ignore")


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(re.sub(r"\s+", " ", "".join(self.cell)).strip())
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.tables[-1].append(self.row)
            self.row = None

    def handle_data(self, d):
        if self.cell is not None:
            self.cell.append(d)


def tables(page):
    p = Tables()
    p.feed(page)
    return [t for t in p.tables if t]


def text(page):
    page = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))


def kv(tbls):
    """Flatten 2-column tables into {label: value}."""
    out = {}
    for t in tbls:
        for r in t:
            if len(r) == 2 and r[0] and r[0] not in out:
                out[r[0]] = r[1]
    return out


def num(s):
    m = re.search(r"-?[\d,]+(?:\.\d+)?", s or "")
    return float(m.group().replace(",", "")) if m else None


def parse_date(s):
    s = re.sub(r"^[A-Za-z]+,\s*", "", (s or "").strip()).rstrip("T").strip()
    for f in ("%b %d, %Y", "%B %d, %Y", "%d %b %Y"):
        try:
            return dt.datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None


def calendar_events():
    ipos = {}
    for board, url in CALENDARS.items():
        t = get(url).replace('\\"', '"')
        pat = (r'ipo_news/([a-z0-9-]+)/(\d+)/#\d+","children":\["\$","span",null,'
               r'\{"className":"small","children":"([^"]+?) IPO (Opens|Closes)[^"]*? on ([A-Z][a-z]{2} \d{1,2}, \d{4})"')
        for slug, pid, name, kind, date in re.findall(pat, t):
            d = ipos.setdefault(slug, {"slug": slug, "id": pid, "board": board,
                                       "name": json.loads(f'"{name}"')})
            d["open" if kind == "Opens" else "close"] = parse_date(date).isoformat()
    lo, hi = TODAY - dt.timedelta(days=WINDOW_BACK), TODAY + dt.timedelta(days=WINDOW_AHEAD)
    keep = {}
    for slug, d in ipos.items():
        days = [dt.date.fromisoformat(d[k]) for k in ("open", "close") if k in d]
        if days and lo <= max(days) and min(days) <= hi:
            keep[slug] = d
    return keep


def ipo_details(d):
    page = get(f"{CG}/ipo/{d['slug']}/{d['id']}/")
    tb = tables(page)
    f = kv(tb)
    band = re.findall(r"[\d,.]+", f.get("Price Band", "") or f.get("Issue Price", ""))
    d["price_low"], d["price_high"] = (num(band[0]), num(band[-1])) if band else (None, None)
    d["lot"] = num(f.get("Lot Size"))
    d["issue_size"] = f.get("Total Issue Size", "")
    d["sale_type"] = f.get("Sale Type", "")
    d["fresh"] = f.get("Fresh Issue", "")
    d["ofs"] = f.get("Offer for Sale", "")
    for t in tb:
        if t and t[0][:1] == ["Application"]:
            for r in t[1:]:
                if len(r) >= 4:
                    key = r[0].lower().replace(" ", "").replace("(", "_").replace(")", "")
                    d[f"app_{key}"] = {"lots": num(r[1]), "shares": num(r[2]), "amount": num(r[3])}
        if t and t[0][:1] == ["Investor Category"]:
            d["quota"] = {r[0]: r[1] for r in t[1:] if len(r) >= 2}
    d["financials"] = next(([" | ".join(r) for r in t] for t in tb if t and t[0][:1] == ["Period Ended"]), [])
    d["kpi"] = next(([" | ".join(r) for r in t] for t in tb if t and t[0][:1] == ["KPI"]), [])
    d["valuation"] = next(([" | ".join(r) for r in t] for t in tb if t and t[0][:1] == ["Valuation Metric"]), [])
    d["listing_date_hint"] = parse_date(f.get("Listing Date", "")) and parse_date(f.get("Listing Date")).isoformat()
    m = re.search(r"\b(?:is a|an?) ([^.]{0,160}?(?:company|manufacturer|provider|platform|hospital|bank)[^.]{0,120})\.", text(page))
    d["about"] = m.group(1) if m else ""
    reg = re.search(r"(KFin Technologies|MUFG Intime|Link Intime|Bigshare Services|Skyline Financial|Cameo Corporate|"
                    r"Maashitla Securities|Purva Sharegistry|Integrated Registry|Kfin Technologies)", page)
    d["registrar"] = reg.group(1) if reg else None
    d["listing_day"] = listing_day(tb)


def listing_day(tb):
    """Listing-day prices from the 'Price Details | BSE | NSE' table, once the IPO has listed."""
    t = next((t for t in tb if t and t[0][:1] == ["Price Details"]), None)
    if not t:
        return None
    hdr = t[0]
    col = hdr.index("NSE") if "NSE" in hdr else len(hdr) - 1
    rows = {r[0]: num(r[col]) if len(r) > col else None for r in t[1:]}
    issue, open_, close = rows.get("Final Issue Price"), rows.get("Open"), rows.get("Last Trade")
    if not (issue and open_):
        return None
    pct = lambda v: round((v / issue - 1) * 100, 2) if v else None  # noqa: E731
    return {"issue": issue, "open": open_, "high": rows.get("High"), "low": rows.get("Low"), "close": close,
            "open_pct": pct(open_), "close_pct": pct(close)}


def subscription(d):
    page = get(f"{CG}/ipo_subscription/{d['slug']}/{d['id']}/")
    f = kv(tables(page))
    sub = {}
    for k, label in (("qib", "Qualified Institutional"), ("nii", "Non Institutional"),
                     ("snii", "sNII"), ("bnii", "bNII"), ("retail", "Retail Individual"),
                     ("employee", "Employee Reservations"), ("total", "Total Subscription")):
        v = next((val for key, val in f.items() if key.startswith(label) and val.endswith("x")), None)
        if v:
            sub[k] = num(v)
    m = re.search(r"subscribed\s*([\d.]+)x as of\s*([A-Z][a-z]{2} \d{1,2}, \d{4} \d{1,2}:\d{2})", text(page))
    sub["as_of"] = m.group(2) if m else None
    # Embedded bidding JSON: retail shares on offer and application count -> real allotment odds
    raw = page.replace('\\"', '"')
    best = None
    for mm in re.finditer(r'\{"id":\d+,"ipo_id":\d+.*?"no_of_application":"?[\d.]*"?[^}]*\}', raw):
        blob = mm.group(0)
        g = lambda k: (re.search(rf'"{k}":"?([\d.]+)"?', blob) or [None, None])[1]  # noqa: E731
        row = {"date": (re.search(r'"date_added":"([^"]+)"', blob) or [None, ""])[1],
               "rii_offered": num(g("rii_offered")), "rii_bid": num(g("rii_shares_bid_for")),
               "applications": num(g("total_application")), "snii": num(g("nii_small")), "bnii": num(g("nii_big"))}
        if row["applications"] and (best is None or row["date"] > best["date"]):
            best = row
    if best:
        sub["applications"], sub["rii_offered"] = best["applications"], best["rii_offered"]
        sub.setdefault("snii", best["snii"])
        sub.setdefault("bnii", best["bnii"])
    d["subscription"] = sub
    for key, label in (("allotment", "Finalisation of Basis of Allotment"), ("refund", "Initiation of Refunds"),
                       ("demat_credit", "Credit of Shares to Demat Account"), ("listing", "IPO Listing Date"),
                       ("open", "IPO opens On"), ("close", "IPO Closes On")):
        p = parse_date(f.get(label, ""))
        if p:
            d[key] = p.isoformat()
    for t in tables(page):  # anchor summary
        if t and t[0][:1] == ["Bid Date"]:
            d["anchor"] = {r[0]: r[1] for r in t if len(r) == 2}


def gmp(d):
    try:
        page = get(f"https://www.investorgain.com/chr-gmp/{d['slug']}/{d['id']}/")
    except Exception as e:  # noqa: BLE001
        d["gmp"] = {"error": str(e)}
        return
    trend = next((t for t in tables(page) if t and t[0][:2] == ["GMP Date", "GMP"]), [])
    rows = []
    for r in trend[1:]:
        m = re.search(r"₹\s*(-?[\d,]+)\s*\((-?[\d.]+)%\)", r[1])
        if m:
            rows.append({"when": r[0], "gmp": num(m.group(1)), "pct": float(m.group(2)),
                         "trend": r[-1] if len(r) > 4 else ""})
    d["gmp"] = {"latest": rows[0] if rows else None, "history": rows[:8], "all": rows}


def ipowatch():
    """Second GMP source: {lowercased name: {'gmp': ₹, 'pct': %}}."""
    page = get("https://ipowatch.in/ipo-grey-market-premium-latest-ipo-gmp/")
    out = {}
    for t in tables(page):
        if not t or t[0][:2] != ["Company", "GMP*"]:
            continue
        for r in t[1:]:
            name = re.sub(r"\s*(Upcoming|Open|Closed|Listed)\s*$", "", r[0]).strip().lower()
            m = re.search(r"\((-?[\d.]+)%\)", r[4] if len(r) > 4 else "")
            if m:
                out[name] = {"gmp": num(r[1]), "pct": float(m.group(1))}
    return out


def match(name, table):
    """Find an entry whose key shares the IPO's first two words (names differ across sites)."""
    norm = lambda s: re.sub(r"[^a-z0-9 ]", " ", s.lower()).split()  # noqa: E731
    words = norm(name)
    for n in (2, 1):
        key = words[:n]
        if n == 1 and len(key[0]) < 4:
            break
        for k, v in table.items():
            if norm(k)[:n] == key:
                return v
    return None


def telegram_gmp(msgs, name):
    """Anant's own GMP posts, e.g. 'Jio ipo latest GMP 220 Rs (19%)'. Latest wins."""
    first = re.sub(r"[^a-z0-9]", "", name.lower().split()[0])
    hit = None
    for m in msgs:
        t = m["text"]
        if first in re.sub(r"[^a-z0-9 ]", "", t.lower()) and "gmp" in t.lower():
            mm = re.search(r"GMP\D{0,15}?(\d[\d,]*)\s*(?:Rs|₹)?\.?\s*\((\d+(?:\.\d+)?)\s*%\)", t, re.I)
            if mm:
                hit = {"gmp": num(mm.group(1)), "pct": float(mm.group(2)), "when": m["when"], "url": m["url"]}
    return hit


def videos():
    feed = get(f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}")
    out = []
    for e in re.findall(r"<entry>(.*?)</entry>", feed, flags=re.S):
        vid = re.search(r"<yt:videoId>([^<]+)", e).group(1)
        title = html.unescape(re.search(r"<title>([^<]*)", e).group(1))
        pub = re.search(r"<published>([^<]+)", e).group(1)
        desc = html.unescape((re.search(r"<media:description>(.*?)</media:description>", e, re.S) or [None, ""])[1])
        out.append({"id": vid, "title": title, "published": pub, "url": f"https://www.youtube.com/watch?v={vid}",
                    "ipo": bool(re.search(r"\bipo|आईपीओ", title + " " + desc[:300], re.I))})
    return out


def _transcript_api(vid):
    r = subprocess.run(["uvx", "--from", "youtube-transcript-api", "youtube_transcript_api", vid,
                        "--languages", "hi", "en", "--format", "text"],
                       capture_output=True, text=True, timeout=240, cwd="/tmp")
    body = r.stdout.replace("\n", " ").strip()
    return "" if r.returncode or body.startswith("Could not retrieve") else body


def _transcript_ytdlp(vid):
    """Fallback: yt-dlp auto-captions (json3) into a temp dir."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["uvx", "yt-dlp", "--skip-download", "--write-auto-subs", "--sub-langs", "hi,en",
                        "--sub-format", "json3", "-o", f"{tmp}/%(id)s.%(ext)s",
                        f"https://www.youtube.com/watch?v={vid}"],
                       capture_output=True, text=True, timeout=240, cwd=tmp)
        for f in sorted(Path(tmp).glob(f"{vid}*.json3")):
            ev = json.loads(f.read_text()).get("events", [])
            return re.sub(r"\s+", " ", "".join(s.get("utf8", "") for e in ev for s in e.get("segs", []) or []))
    return ""


def transcript(vid):
    dest = RAW / "transcripts" / f"{vid}.txt"
    if dest.exists() and dest.stat().st_size > 500:
        return dest
    body = _transcript_api(vid) or _transcript_ytdlp(vid)
    if len(body) < 500:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(body)
    return dest


def telegram(limit=40):
    page = get(TELEGRAM)
    out = []
    for block in re.findall(r'<div class="tgme_widget_message_wrap.*?(?=<div class="tgme_widget_message_wrap|\Z)', page, re.S):
        m = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', block, re.S)
        t = re.search(r'<time datetime="([^"]+)"', block)
        link = re.search(r'data-post="([^"]+)"', block)
        body = text(m.group(1)).strip() if m else ""
        if body:
            out.append({"when": t.group(1) if t else None, "text": body,
                        "url": f"https://t.me/{link.group(1)}" if link else TELEGRAM})
    return out[-limit:]


def main():
    numbers_only = "--numbers" in sys.argv  # GitHub job: no YouTube (cloud IPs are blocked)
    DATA.mkdir(exist_ok=True)
    RAW.mkdir(exist_ok=True)
    errors = []
    ipos = calendar_events()
    for d in ipos.values():
        for step in (ipo_details, subscription, gmp):
            try:
                step(d)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{d['slug']} {step.__name__}: {e}")
    tg = []
    try:
        tg = telegram()
    except Exception as e:  # noqa: BLE001
        errors.append(f"telegram: {e}")
    try:
        ipw = ipowatch()
    except Exception as e:  # noqa: BLE001
        ipw = {}
        errors.append(f"ipowatch: {e}")
    for d in ipos.values():
        d["gmp_ipowatch"] = match(d["name"], ipw)
        d["gmp_anant"] = telegram_gmp(tg, d["name"])

    vids = []
    if not numbers_only:
        try:
            vids = videos()
        except Exception as e:  # noqa: BLE001
            errors.append(f"rss: {e}")
        seen_path = DATA / "seen_videos.json"
        seen = json.loads(seen_path.read_text()) if seen_path.exists() else {}
        for v in vids:
            if v["ipo"]:
                p = transcript(v["id"])
                v["transcript"] = str(p.relative_to(ROOT)) if p else None
                v["new"] = v["id"] not in seen
                seen.setdefault(v["id"], {"title": v["title"], "published": v["published"]})
        seen_path.write_text(json.dumps(seen, indent=1, ensure_ascii=False))

    fetched = dt.datetime.now(IST).isoformat(timespec="minutes")
    auto = {"fetched_at": fetched, "ipos": ipos, "videos": vids, "telegram": tg, "errors": errors}
    (DATA / "auto.json").write_text(json.dumps(auto, indent=1, ensure_ascii=False))

    lines = [f"# IPO digest {fetched}", "", f"Errors: {errors or 'none'}", "", "## IPOs in window"]
    for d in sorted(ipos.values(), key=lambda x: x.get("close", "")):
        s, g = d.get("subscription", {}), (d.get("gmp") or {}).get("latest") or {}
        g2, ga = d.get("gmp_ipowatch") or {}, d.get("gmp_anant") or {}
        lines.append(f"- **{d['name']}** ({d['board']}, slug `{d['slug']}`) open {d.get('open')} close {d.get('close')} "
                     f"listing {d.get('listing')} · ₹{d.get('price_low')}–{d.get('price_high')} lot {d.get('lot')} · "
                     f"sub total {s.get('total')}x retail {s.get('retail')}x NII {s.get('nii')}x QIB {s.get('qib')}x "
                     f"apps {s.get('applications')} (as of {s.get('as_of')}) · GMP IG {g.get('pct')}% {g.get('trend', '')} "
                     f"/ IPOWatch {g2.get('pct')}% / Anant {ga.get('pct')}% · registrar {d.get('registrar')}")
        if d.get("financials"):
            lines += ["  - financials: " + " ;; ".join(d["financials"][:6])]
    lines += ["", "## Anant's IPO videos (RSS, newest first)"]
    for v in vids:
        if v["ipo"]:
            lines.append(f"- {'NEW ' if v.get('new') else ''}{v['published'][:16]} [{v['title']}]({v['url']}) "
                         f"transcript: {v.get('transcript')}")
    lines += ["", "## Telegram (latest last)"]
    lines += [f"- {m['when']}: {m['text'][:400]}" for m in tg]
    (RAW / "digest.md").write_text("\n".join(lines))
    print("\n".join(lines[:60]))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
