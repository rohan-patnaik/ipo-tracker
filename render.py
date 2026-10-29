"""Render data/{auto,notes,results,backfill}.json into site/index.html + site/ipo.ics (static, self-contained).

`python3 render.py --strict` exits 2 when the self-check finds a call that breaks the rules (used before publishing).
"""
import datetime as dt
import html
import json
import os
import re
import sys
from pathlib import Path

import rules

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / "config.json").read_text())
AUTO = json.loads((ROOT / "data" / "auto.json").read_text())
NOTES = json.loads((ROOT / "data" / "notes.json").read_text())


def load(name, default):
    p = ROOT / "data" / name
    return json.loads(p.read_text()) if p.exists() else default


RESULTS = load("results.json", {"items": {}})["items"]
BACKFILL = load("backfill.json", {"items": []})["items"]
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
NOW = dt.datetime.fromisoformat(os.environ["IPO_NOW"]) if os.environ.get("IPO_NOW") else dt.datetime.now(IST)  # IPO_NOW: tests only
TODAY = NOW.date()
BENCH = CFG["gmp_benchmark_pct"]
CAP = CFG["capital_inr"]
HOLIDAYS = CFG.get("holidays", {})
SITE = CFG["site_url"].rstrip("/")
e = html.escape

REGISTRARS = {
    "KFin": "https://ipostatus.kfintech.com/",
    "MUFG": "https://in.mpms.mufg.com/Initial_Offer/public-issues.html",
    "Link Intime": "https://in.mpms.mufg.com/Initial_Offer/public-issues.html",
    "Bigshare": "https://ipo.bigshareonline.com/IPO_Status.html",
    "Skyline": "https://www.skylinerta.com/ipo.php",
    "Cameo": "https://ipo.cameoindia.com/",
    "Maashitla": "https://maashitla.com/allotment-status/public-issues",
    "Purva": "https://www.purvashare.com/investor-service/ipo-query",
}


# ---------- formatting ----------
def inr(n):
    if n is None:
        return "—"
    n = int(round(n))
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return ("-" if n < 0 else "") + "₹" + s


def lakh(n):
    return f"{n / 1e5:.1f} lakh" if n >= 1e5 else f"{n:,.0f}"


def d(iso):
    return dt.date.fromisoformat(iso) if iso else None


def short(iso):
    v = d(iso)
    return v.strftime("%a %-d %b") if v else "—"


def x(v):
    return "—" if v is None else (f"{v:.2f}×" if v < 10 else f"{v:.1f}×" if v < 100 else f"{v:.0f}×")


def pct(v, signed=True):
    return "—" if v is None else (f"{v:+.1f}%" if signed else f"{v:.1f}%")


def is_closed(i):
    c = d(i.get("close"))
    return bool(c) and (TODAY > c or (TODAY == c and NOW.hour >= 17))


# ---------- derived numbers ----------
def odds(i):
    """Retail allotment odds for one minimum application. Uses retail lots ÷ applications when known."""
    s = i.get("subscription") or {}
    r, apps, offered, lot = s.get("retail"), s.get("applications"), s.get("rii_offered"), i.get("lot")
    live = not is_closed(i)
    tail = " so far" if live else ""
    if r is None:
        return "Not open yet", "Shown once bidding starts"
    if r <= 1:
        return "Full allotment" + tail, "Retail is undersubscribed, so every valid bid gets its shares"
    if apps and offered and lot:
        lots = offered / lot
        p = min(1.0, lots / apps)
        note = f"{lakh(lots)} retail lots for {lakh(apps)} applications"
        if p >= 0.99:
            return "Almost certain" + tail, note + ". Everyone should get at least 1 lot"
        return f"About {p * 100:.0f}%{tail}", note + (". Falls as last-day bids come in" if live else "")
    return f"1 in {r:.0f}{tail}" if r >= 1.5 else f"1 in 1–2{tail}", "Rough estimate from retail subscription"


def registrar_url(name):
    for k, v in REGISTRARS.items():
        if name and k.lower() in name.lower():
            return v
    return None


def allot_links(i):
    """Allotment-check links. Each was opened and verified on 2026-10-21; BSE's page now redirects or blocks, so it's left out."""
    links = [f'<a href="https://www.chittorgarh.com/ipo_allotment_status/{e(i["slug"])}/{e(i["id"])}/" target="_blank" rel="noopener">Chittorgarh (this IPO)</a>']
    ru = registrar_url(i.get("registrar"))
    if ru:
        links.append(f'<a href="{ru}" target="_blank" rel="noopener">{e(i["registrar"])} (registrar)</a>')
    return " · ".join(links)


def gmp_sources(i):
    out = []
    g = (i.get("gmp") or {}).get("latest") or {}
    main = (i.get("gmp") or {}).get("source", "InvestorGain")
    if g.get("pct") is not None:
        out.append((main, g["pct"]))
    if main != "IPOWatch" and (i.get("gmp_ipowatch") or {}).get("pct") is not None:
        out.append(("IPOWatch", i["gmp_ipowatch"]["pct"]))
    if (i.get("gmp_anant") or {}).get("pct") is not None:
        out.append(("Anant", i["gmp_anant"]["pct"]))
    return out


DEFAULT_NOTE = {"anant": "—", "anant_said": ["Not covered by Anant yet."], "risk": "—"}

ipos = []
for slug, a in AUTO["ipos"].items():
    n = NOTES["ipos"].get(slug)
    if a["board"] == "sme" and (not n or n.get("anant") != "A"):
        continue  # SME only when Anant rates it A
    a = dict(a)
    a.update(n or DEFAULT_NOTE)
    a["has_note"] = bool(n)
    a["lot_amt"] = (a.get("lot") or 0) * (a.get("price_high") or 0)
    g = (a.get("gmp") or {}).get("latest") or {}
    a["gmp_pct"], a["gmp_rs"], a["gmp_trend"] = g.get("pct"), g.get("gmp"), g.get("trend", "")
    # the call: computed by the last-day rule; locked at 2 pm on the last day (data/results.json)
    if a.get("tracked", True) is False:
        a["stage"], a["checks"], a["warn"], a["lean"] = "closed", [], None, None
        a["condition"] = a.get("condition", "Closed before the tracker started.")
    else:
        dec = rules.decide(a, BENCH, NOW) if a.get("close") else {"stage": "watching", "call": None, "lean": "Dates not out",
                                                                   "checks": [], "warn": None, "why": ""}
        a.update(stage=dec["stage"], checks=dec["checks"], warn=dec["warn"], lean=dec["lean"])
        locked = RESULTS.get(slug)
        if dec["stage"] in ("final", "closed") and locked:
            a["verdict"], a["condition"] = locked["call"], locked.get("why", "")
            a["checks"] = [tuple(c) for c in locked.get("checks", [])] or a["checks"]
            a["warn"] = locked.get("warn")
        elif dec["stage"] == "watching":
            a["verdict"], a["condition"] = "WATCH", dec["lean"] + ". " + dec["why"]
        else:
            a["verdict"], a["condition"] = dec["call"], dec["why"]
    a["lots"] = 1 if a["verdict"] in ("APPLY", "CONDITIONAL") else 0
    a["block"] = a["lot_amt"] * a["lots"]
    a["closed"] = is_closed(a)
    a["expected"] = a["price_high"] * (1 + a["gmp_pct"] / 100) if a.get("price_high") and a["gmp_pct"] is not None else None
    src = gmp_sources(a)
    a["gmp_spread"] = (max(p for _, p in src) - min(p for _, p in src)) if len(src) > 1 else 0
    ipos.append(a)

RANK = {"APPLY": 0, "CONDITIONAL": 1, "WATCH": 2, "SKIP": 3}
live = sorted([i for i in ipos if not i["closed"]],
              key=lambda i: (i.get("close", ""), RANK.get(i["verdict"], 9), -(i["gmp_pct"] or 0)))
closed = sorted([i for i in ipos if i["closed"] and (d(i.get("listing")) or TODAY) >= TODAY],
                key=lambda i: i.get("listing") or "")
skipped_sme = [a["name"] for s, a in AUTO["ipos"].items() if a["board"] == "sme" and
               NOTES["ipos"].get(s, {}).get("anant") != "A" and not is_closed(a)]

# ---------- money: peak blocked at once (blocked from last day until allotment) ----------
spans = [(d(i["close"]), d(i.get("allotment")) or d(i["close"]) + dt.timedelta(days=3), i["block"])
         for i in live if i["verdict"] in ("APPLY", "CONDITIONAL") and i["block"]]
horizon = [TODAY + dt.timedelta(days=k) for k in range(30)]
peak, peak_day = 0, None
for day in horizon:
    tot = sum(b for s, t, b in spans if s <= day <= t)
    if tot > peak:
        peak, peak_day = tot, day
peak_pct = min(100, 100 * peak / CAP)

# ---------- self-check (notes must be well-formed; the call itself is computed) ----------
problems = []
for slug, n in NOTES["ipos"].items():
    nm = n.get("name") or slug
    if n.get("anant", "—") not in ("A", "A?", "B", "C", "—"):
        problems.append(f"{nm}: anant must be A, A?, B, C or —.")
    if n.get("risk", "—") not in ("Low", "Medium", "High", "—"):
        problems.append(f"{nm}: risk must be Low, Medium or High.")
    ov = n.get("override")
    if ov and (ov.get("verdict") != "SKIP" or not ov.get("reason")):
        problems.append(f"{nm}: an override can only force SKIP, with a reason.")
if peak > CAP:
    problems.append(f"Peak money blocked {inr(peak)} is over the {inr(CAP)} limit. Drop the weakest same-day Apply.")

# ---------- day strip ----------
events = {}
for i in ipos:
    for key, label in (("open", "Opens"), ("close", "Last day"), ("allotment", "Allotment"), ("listing", "Lists")):
        if i.get(key):
            events.setdefault(i[key], []).append((label, i))
last = max([d(i["listing"]) for i in live if i.get("listing")] + [TODAY + dt.timedelta(days=7)])
days = [TODAY + dt.timedelta(days=k) for k in range((last - TODAY).days + 1)]


def day_tag(day):
    iso = day.isoformat()
    if iso in HOLIDAYS:
        return "Holiday", "hol"
    ev = events.get(iso, [])
    if any(lbl == "Last day" and not i["closed"] and (i["verdict"] in ("APPLY", "CONDITIONAL") or i.get("lean", "").startswith("Leaning apply"))
           for lbl, i in ev):
        return "Decide", "act"
    for want, tag in (("Last day", "Closes"), ("Opens", "Opens"), ("Lists", "Listing"), ("Allotment", "Allot")):
        if any(lbl == want for lbl, _ in ev):
            return tag, ""
    return "", ""


chips = []
for day in days:
    tag, cls = day_tag(day)
    iso = day.isoformat()
    names = "; ".join(f"{i['name']}: {lbl.lower()}" for lbl, i in events.get(iso, []))
    if iso in HOLIDAYS:
        names = f"Market holiday ({HOLIDAYS[iso]})" + (f"; {names}" if names else "")
    chips.append(
        f'<button type="button" class="chip{" today" if day == TODAY else ""}{" " + cls if cls else ""}" '
        f'data-day="{iso}" data-say="{e(day.strftime("%A %-d %B"))}: {e(names or "nothing scheduled")}">'
        f'<span class="dw">{day.strftime("%a")}</span><span class="dn">{day.day}</span>'
        f'<span class="dt">{e(tag)}</span></button>')


# ---------- to-do ----------
def listing_plan(i):
    exp, g = i.get("expected"), i.get("gmp_pct")
    if exp is None:
        return "Listing price expectation appears once GMP is quoted."
    head = f"Expected around {inr(exp)} ({pct(g)}) on listing."
    if g is not None and g >= 25:
        return (head + " Strong listing, so use the Rule of 15: watch the first 15 minutes after 10 am, note that low, "
                "hold while it stays above it and sell the moment it breaks.")
    return head + " Average listing, so sell in the pre-open (9:00–9:45 am) with a limit a little under the expected price."


todo = []
for i in live:
    nm, day = e(i["name"]), short(i["close"])
    if i["stage"] == "watching" and (i.get("lean") or "").startswith("Leaning apply"):
        todo.append((i["close"], 0, f"<b>{day}:</b> last day for {nm}. Leaning apply; the final call locks at 2 pm that day."))
    elif i["stage"] == "watching" and i.get("lean") == "Waiting for Anant":
        todo.append((i["close"], 0, f"<b>{day}:</b> last day for {nm}. Waiting for Anant's view; decided at 2 pm that day."))
    elif i["verdict"] == "APPLY":
        tag = "final call" if i["stage"] == "final" else "provisional; final at 2 pm"
        todo.append((i["close"], 0, f"<b>{day}, by 5 pm:</b> apply {nm}, 1 lot ({inr(i['block'])}). <span class=sub2>{tag}</span>"))
    elif i["verdict"] == "CONDITIONAL":
        todo.append((i["close"], 0, f"<b>{day}:</b> {nm}. {e(i['condition'])} Final call at 2 pm."))
for i in ipos:
    applied = (i["verdict"] == "APPLY" and i["stage"] in ("final", "closed")) or (i.get("you") or {}).get("applied")
    if not applied:
        continue
    if i.get("allotment") and d(i["allotment"]) >= TODAY and i["closed"]:
        todo.append((i["allotment"], 1, f"<b>{short(i['allotment'])}, evening:</b> check whether you got {e(i['name'])} "
                                        f"({allot_links(i)})."))
    if i.get("listing") and d(i["listing"]) >= TODAY and i["closed"]:
        todo.append((i["listing"], 2, f"<b>{short(i['listing'])}:</b> {e(i['name'])} lists. {e(listing_plan(i))}"))
todo = [t for _, _, t in sorted(todo)]



# ---------- cells ----------
def gmp_cell(i):
    p = i["gmp_pct"]
    if p is None:
        return '<span class="muted">No GMP yet</span>'
    ok = p >= BENCH
    arrow = {"Upward": "↑", "Strong Upward": "↑↑", "Downward": "↓", "Strong Downward": "↓↓"}.get(i["gmp_trend"], "")
    others = [f"{name} {v:.0f}%" for name, v in gmp_sources(i)[1:]]
    warn = (f'<div class="warnline">Sources differ by {i["gmp_spread"]:.0f} points</div>'
            if i["gmp_spread"] >= 5 else "")
    return (f'<b class="{"ok" if ok else "bad"}">{p:.1f}%</b> <span class="muted">{inr(i["gmp_rs"])}</span>'
            f'<div class="sub2">{e(i["gmp_trend"] or "")} {arrow} · {"clears" if ok else "below"} {BENCH}%</div>'
            f'{("<div class=sub2>" + e(", ".join(others)) + "</div>") if others else ""}{warn}')


def sub_cell(i):
    s = i.get("subscription") or {}
    if s.get("total") is None:
        return '<span class="muted">Opens ' + short(i.get("open")) + "</span>"
    rows = "".join(f"<span>{k}</span><b>{x(s.get(v))}</b>" for k, v in
                   (("Retail", "retail"), ("NII", "nii"), ("QIB", "qib"), ("Total", "total")))
    asof = s.get("as_of") or ""
    return f'<div class="subgrid">{rows}</div><div class="sub2">as of {e(asof[:-6] if asof else "")}</div>'


VERDICT = {"APPLY": ("Apply", "v-apply"), "CONDITIONAL": ("Apply if…", "v-cond"),
           "SKIP": ("Skip", "v-skip"), "WAIT": ("Wait", "v-wait"), "WATCH": ("Watching", "v-wait")}
STAGE = {"provisional": "For now: ", "final": "Final: ", "closed": "", "watching": ""}


def applies_today(i):
    """Last day is today and the call is (or may become) Apply."""
    return i.get("close") == TODAY.isoformat() and not i["closed"] and i["verdict"] in ("APPLY", "CONDITIONAL")


def yes_badge(i):
    if not applies_today(i):
        return ""
    return '<span class="yes">YES · apply today</span>' if i["verdict"] == "APPLY" else '<span class="yes maybe">YES if QIB ≥ 1×</span>'


def label(i):
    text, cls = VERDICT.get(i["verdict"], (i["verdict"], ""))
    return yes_badge(i) + f'<span class="verdict {cls}">{STAGE.get(i.get("stage"), "")}{text}</span>'


def checks_html(i):
    mark = {True: "✓", False: "✗", None: "–"}
    rows = "".join(f'<li class="c{"ok" if ok else "no" if ok is False else "na"}"><span>{mark[ok]}</span> {e(name)}: {e(text)}</li>'
                   for name, ok, text in (i.get("checks") or []))
    warn = f'<li class="cwarn"><span>!</span> {e(i["warn"])}</li>' if i.get("warn") else ""
    return f'<ul class="checks">{rows}{warn}</ul>' if rows or warn else ""
RISK = {"Low": "r-low", "Medium": "r-med", "High": "r-high"}


def days_attr(i):
    return " ".join(i.get(k, "") for k in ("open", "close", "allotment", "listing"))


def row(i):
    o, o_why = odds(i)
    money = (f'<div class="amt">{inr(i["block"])}</div><div class="sub2">1 lot × {inr(i["lot_amt"])}</div>'
             if i["block"] else "")
    exp = f'<div class="sub2">≈ {inr(i["expected"])} expected</div>' if i.get("expected") else ""
    return f"""<tr data-days="{days_attr(i)}" id="row-{e(i['slug'])}">
<td class="c-name" data-l="IPO"><a href="#why-{e(i['slug'])}">{e(i['name'])}</a>
  <div class="sub2">{"SME" if i['board'] == 'sme' else "Mainboard"} · Anant: <b class="cat">{e(i['anant'])}</b></div></td>
<td data-l="Apply window"><div class="v"><b>{short(i.get('open'))} → {short(i.get('close'))}</b><div class="sub2">Last day, UPI mandate by 5 pm</div></div></td>
<td data-l="Allotment"><div class="v">{short(i.get('allotment'))}</div></td>
<td data-l="Listing"><div class="v">{short(i.get('listing'))}{exp}</div></td>
<td data-l="Price and lot"><div class="v"><b>{inr(i.get('price_high'))}</b><div class="sub2">{int(i.get('lot') or 0)} shares = {inr(i['lot_amt'])}</div></div></td>
<td data-l="GMP"><div class="v">{gmp_cell(i)}</div></td>
<td data-l="Subscription"><div class="v">{sub_cell(i)}</div></td>
<td data-l="Allotment odds"><div class="v"><b>{e(o)}</b><div class="sub2">{e(o_why)}</div></div></td>
<td data-l="Risk"><div class="v"><span class="risk {RISK.get(i['risk'], '')}">{e(i['risk'])}</span></div></td>
<td class="c-verdict" data-l="Call"><div class="v">{label(i)}{money}
  <div class="cond">{e(i['condition'])}</div>{checks_html(i)}</div></td>
</tr>"""


def why(i):
    hist = (i.get("gmp") or {}).get("history") or []
    pts = [h for h in reversed(hist) if h["pct"] > 0]
    top = max([h["pct"] for h in pts] + [BENCH * 2])
    spark = "".join(
        f'<span class="bar{" lo" if h["pct"] < BENCH else ""}" style="--h:{max(4, 100 * h["pct"] / top):.0f}%" '
        f'title="{e(h["when"])}: {h["pct"]}%"></span>' for h in pts)
    if spark:
        spark += f'<span class="gate" style="bottom:{100 * BENCH / top:.0f}%"><em>{BENCH}%</em></span>'
    anchor = i.get("anchor") or {}
    fin = [r for r in i.get("financials", []) if r.startswith(("Period Ended", "Total Income", "Profit After Tax"))]
    fin_html = "".join(f"<tr>{''.join(f'<td>{e(c.strip())}</td>' for c in r.split('|'))}</tr>" for r in fin)
    video = f'<a class="vid" href="{e(i["video"])}" target="_blank" rel="noopener">Watch his take</a>' if i.get("video") else ""
    extra = f'<p class="note">{e(i["lots_note"])}</p>' if i.get("lots_note") else ""
    src = gmp_sources(i)
    src_html = " · ".join(f"{n} {v:.1f}%" for n, v in src)
    ga = i.get("gmp_anant")
    anant_post = (f' <a href="{e(ga["url"])}" target="_blank" rel="noopener">Anant\'s post</a>' if ga else "")
    when = f"last day {short(i.get('close'))}" if not i["closed"] else f"lists {short(i.get('listing'))}"
    return f"""<section class="card" id="why-{e(i['slug'])}">
<header><h3>{e(i['name'])}</h3>{label(i)}<span class="when">{when}</span>{video}</header>
<div class="split">
  <div><h4>What Anant said{(" (latest view " + e(i["anant_updated"]) + ")") if i.get("anant_updated") else ""}</h4><ul>{''.join(f'<li>{e(s)}</li>' for s in i.get('anant_said', []))}</ul>{extra}
    <h4 class="gap">Listing day plan</h4><p>{e(listing_plan(i))}</p>
    <h4 class="gap">Check allotment ({short(i.get('allotment'))})</h4><p>{allot_links(i)}</p></div>
  <div><h4>Numbers</h4>
    <div class="spark" aria-label="GMP trend, oldest to newest">{spark or '<span class="muted">No GMP history yet</span>'}</div>
    <p class="sub2">GMP % over the last {len(hist)} readings, oldest left; dashed line is your {BENCH}% gate</p>
    {f'<p class="sub2">Today by source: {e(src_html)}{anant_post}</p>' if src else ''}
    <p><b>Risk: {e(i['risk'])}.</b> {e(i.get('risk_why', ''))}</p>
    {f'<p class="sub2">Anchor book: {e(anchor.get("% of QIBs", "—"))} of QIB quota, bid {e(anchor.get("Bid Date", ""))}</p>' if anchor else ''}
    {f'<table class="fin">{fin_html}</table><p class="sub2">₹ crore</p>' if fin_html else ''}
    <p class="sub2"><a href="https://www.chittorgarh.com/ipo/{e(i['slug'])}/{e(i['id'])}/" target="_blank" rel="noopener">Chittorgarh page</a> ·
    <a href="https://www.chittorgarh.com/ipo_subscription/{e(i['slug'])}/{e(i['id'])}/" target="_blank" rel="noopener">Live subscription</a></p>
  </div>
</div></section>"""


def closed_row(i):
    who = "your call" if i.get("tracked", True) else "rule's call (before the tracker)"
    applied = i["verdict"] in ("APPLY", "CONDITIONAL") or (i.get("you") or {}).get("applied")
    plan = listing_plan(i) if applied else "Skipped. Listed here so its result lands in the track record."
    return (f"<tr><td data-l='IPO'><b>{e(i['name'])}</b> <span class='sub2'>Anant: {e(i['anant'])} · "
            f"{who}: {VERDICT.get(i['verdict'], (i['verdict'],))[0]}</span></td>"
            f"<td data-l='Allotment'>{short(i.get('allotment'))}<div class='sub2'>{allot_links(i)}</div></td>"
            f"<td data-l='Listing'>{short(i.get('listing'))}</td><td data-l='GMP'>{gmp_cell(i)}</td>"
            f"<td data-l='Subscribed'>{x((i.get('subscription') or {}).get('total'))}</td>"
            f"<td data-l='Plan' class='cond'>{e(plan)}</td></tr>")


# ---------- track record ----------
def rule_call(anant, gmp, board):
    if gmp is None or anant is None:
        return None
    ok = anant in ("A", "A?") and gmp >= BENCH and (board != "sme" or anant == "A")
    return "APPLY" if ok else "SKIP"


record = []
seen = set()
for slug, it in RESULTS.items():
    seen.add(slug)
    call = it.get("call") if it.get("tracked", True) else rule_call(it.get("anant"), it.get("gmp_at_close"), it.get("board"))
    record.append({**it, "call_used": call, "source": "tracker" if it.get("tracked", True) else "rule"})
for it in BACKFILL:
    if it.get("slug") in seen:
        continue
    record.append({**it, "call_used": rule_call(it.get("anant"), it.get("gmp_at_close"), it.get("board")),
                   "source": "backfill"})
record.sort(key=lambda r: r.get("close") or "", reverse=True)
listed = [r for r in record if r.get("listed") and r.get("list_close_pct") is not None]


def stats(rows):
    if not rows:
        return None
    c = [r["list_close_pct"] for r in rows]
    o = [r["list_open_pct"] for r in rows if r.get("list_open_pct") is not None]
    return {"n": len(rows), "avg": sum(c) / len(c), "avg_open": (sum(o) / len(o)) if o else None,
            "win": 100 * sum(1 for v in c if v > 0) / len(c), "worst": min(c)}


def stat_row(label, rows):
    s = stats(rows)
    if not s:
        return f"<tr><td>{e(label)}</td><td colspan=5 class='muted'>No listings yet</td></tr>"
    return (f"<tr><td>{e(label)}</td><td>{s['n']}</td><td>{pct(s['avg_open'])}</td><td><b>{pct(s['avg'])}</b></td>"
            f"<td>{s['win']:.0f}%</td><td>{pct(s['worst'])}</td></tr>")


def bucket(lo, hi):
    return [r for r in listed if r.get("gmp_at_close") is not None and lo <= r["gmp_at_close"] < hi]


picks = [r for r in listed if r["call_used"] == "APPLY"]
skips = [r for r in listed if r["call_used"] == "SKIP"]
calib = "".join([
    stat_row(f"Your rule says apply (A + GMP ≥ {BENCH}%)", picks),
    stat_row("Your rule says skip", skips),
    stat_row("Anant: A", [r for r in listed if r.get("anant") in ("A", "A?")]),
    stat_row("Anant: B", [r for r in listed if r.get("anant") == "B"]),
    stat_row("Anant: C", [r for r in listed if r.get("anant") == "C"]),
    stat_row("GMP under 10%", bucket(-100, 10)),
    stat_row("GMP 10–15%", bucket(10, 15)),
    stat_row("GMP 15–20%", bucket(15, 20)),
    stat_row("GMP 20–30%", bucket(20, 30)),
    stat_row("GMP 30% or more", bucket(30, 1000)),
])
sp = stats(picks)
headline_stat = (f"When your rule said apply, listings closed {pct(sp['avg'])} on average across {sp['n']} IPOs, "
                 f"and {sp['win']:.0f}% of them closed above the issue price." if sp else
                 "The first results arrive after this week's listings.")


def you_cell(r):
    y = r.get("you") or {}
    if not y:
        return "<span class='muted'>—</span>"
    if not y.get("applied"):
        return "Didn't apply"
    if y.get("allotted") is None:
        return "Applied"
    if not y.get("allotted"):
        return "Applied, not allotted"
    gain = y.get("gain_inr")
    return "Allotted" + (f", {inr(gain)}" if gain is not None else "")


rec_rows = "".join(
    f"<tr><td data-l='IPO'><b>{e(r['name'])}</b><div class='sub2'>{'SME' if r.get('board') == 'sme' else 'Mainboard'} · "
    f"closed {short(r.get('close'))}{' · from his videos' if r['source'] == 'backfill' else ''}</div></td>"
    f"<td data-l='Anant'>{e(r.get('anant') or '—')}</td><td data-l='GMP at close'>{pct(r.get('gmp_at_close'), False)}</td>"
    f"<td data-l='Call'><span class='verdict {VERDICT.get(r['call_used'] or '', ('', 'v-wait'))[1]}'>"
    f"{VERDICT.get(r['call_used'] or '', ('—',))[0]}</span></td>"
    f"<td data-l='Listing open'>{pct(r.get('list_open_pct')) if r.get('listed') else '<span class=muted>Lists ' + short(r.get('listing')) + '</span>'}</td>"
    f"<td data-l='Listing close'><b class='{'ok' if (r.get('list_close_pct') or 0) > 0 else 'bad'}'>{pct(r.get('list_close_pct')) if r.get('listed') else ''}</b></td>"
    f"<td data-l='You'>{you_cell(r)}</td></tr>"
    for r in record)


# ---------- calendar (.ics) ----------
def ics_dt(day, hh, mm):
    return dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=IST).astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def fold(line):
    b = line.encode("utf-8")
    out, cur = [], b""
    for ch in line:
        c = ch.encode("utf-8")
        if len(cur) + len(c) > 73:
            out.append(cur)
            cur = b" " + c
        else:
            cur += c
    out.append(cur)
    return b"\r\n".join(out).decode("utf-8") if len(b) > 73 else line


def esc(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


cal = []


def add_event(uid, day, start, mins, title, desc, url, alarms):
    st = dt.datetime(day.year, day.month, day.day, *start, tzinfo=IST)
    en = st + dt.timedelta(minutes=mins)
    ev = ["BEGIN:VEVENT", f"UID:{uid}@ipo-tracker", f"DTSTAMP:{NOW.astimezone(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
          f"DTSTART:{st.astimezone(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
          f"DTEND:{en.astimezone(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
          f"SUMMARY:{esc(title)}", f"DESCRIPTION:{esc(desc)}", f"URL:{url}"]
    for a in alarms:
        ev += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{esc(title)}", f"TRIGGER:{a}", "END:VALARM"]
    ev.append("END:VEVENT")
    cal.extend(ev)


for i in ipos:
    page = f"{SITE}/#why-{i['slug']}"
    close, allot, listing = d(i.get("close")), d(i.get("allotment")), d(i.get("listing"))
    v = i["verdict"]
    if close and not i["closed"] and i.get("lean") != "Leaning skip" and v != "SKIP":
        add_event(f"{i['slug']}-morning", close, (11, 30), 15, f"Last day: {i['name']} IPO, provisional call on the page",
                  "Final call locks at 2 pm. " + i["condition"], page, ["-PT0M"])
        title = (f"Apply {i['name']} IPO: 1 lot, {inr(i['lot_amt'])} by 5 pm" if v == "APPLY" and i["stage"] == "final"
                 else f"Final call for {i['name']} IPO: open the page")
        add_event(f"{i['slug']}-final", close, (14, 15), 30, title,
                  "If the final call is Apply: bid 1 lot at cut-off and approve the UPI mandate before 5 pm.", page, ["-PT0M"])
    if (v == "APPLY" and i["stage"] in ("final", "closed") and i.get("tracked", True)) or (i.get("you") or {}).get("applied"):
        if allot and allot >= TODAY:
            add_event(f"{i['slug']}-allot", allot, (18, 0), 15, f"Allotment out: {i['name']}",
                      "Check whether you got shares: " + (registrar_url(i.get("registrar")) or "see the tracker page"),
                      registrar_url(i.get("registrar")) or page, ["-PT0M"])
        if listing and listing >= TODAY:
            add_event(f"{i['slug']}-list", listing, (9, 0), 45, f"{i['name']} lists today (if allotted)",
                      listing_plan(i), page, ["-PT0M"])

ics = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//rohan-patnaik//ipo-tracker//EN", "CALSCALE:GREGORIAN",
       "METHOD:PUBLISH", "X-WR-CALNAME:IPO tracker", "X-PUBLISHED-TTL:PT1H", "REFRESH-INTERVAL;VALUE=DURATION:PT1H"]
ics += cal + ["END:VCALENDAR"]

# ---------- page ----------
CSS = """
:root{--bg:#f0eee6;--paper:#faf9f5;--paper2:#f4f2ec;--ink:#141413;--muted:#6b6a65;--accent:#b5532f;--accent-ink:#faf9f5;
--sel:#141413;--sel-ink:#faf9f5;--tint:#e9e5d9;--line:#e1ddd1;--warn:#9a4a12;--orange:#e0700b;--track:#e4e0d4;
--good:#2f6b3a;--good-bg:#e3ecd9;--bad:#a3341f;--bad-bg:#f3ddd3;--mid:#8a5a00;--mid-bg:#f3e6c8;color-scheme:light}
@media(prefers-color-scheme:light){:root:has(#tt:checked){--bg:#1f1e1d;--paper:#272624;--paper2:#2c2b28;--ink:#f0eee6;--muted:#a8a49a;--accent:#e08a66;--accent-ink:#1f1e1d;--sel:#f0eee6;--sel-ink:#1f1e1d;--tint:#2f2d29;--line:#3b3a36;--warn:#f2b27a;--orange:#f59e42;--track:#3b3a36;--good:#9fd18f;--good-bg:#26351f;--bad:#f0a08a;--bad-bg:#3d241d;--mid:#f2c46b;--mid-bg:#3a3020;color-scheme:dark}}
@media(prefers-color-scheme:dark){:root:not(:has(#tt:checked)){--bg:#1f1e1d;--paper:#272624;--paper2:#2c2b28;--ink:#f0eee6;--muted:#a8a49a;--accent:#e08a66;--accent-ink:#1f1e1d;--sel:#f0eee6;--sel-ink:#1f1e1d;--tint:#2f2d29;--line:#3b3a36;--warn:#f2b27a;--orange:#f59e42;--track:#3b3a36;--good:#9fd18f;--good-bg:#26351f;--bad:#f0a08a;--bad-bg:#3d241d;--mid:#f2c46b;--mid-bg:#3a3020;color-scheme:dark}}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;font-size:15px;line-height:1.45;background:var(--bg);color:var(--ink);font-variant-numeric:tabular-nums}
a{color:var(--accent)}
.wrap{max-width:1240px;margin:0 auto;padding:0 16px 48px}
.top{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 0 0}
.bar1{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
h1{font-size:20px;margin:0;flex:1;letter-spacing:-.01em}
.pill{border:1px solid var(--line);background:var(--paper);border-radius:999px;padding:6px 12px;font-size:13px;color:var(--muted);text-decoration:none}
.pill b{color:var(--ink)}
a.pill{color:var(--accent);font-weight:600;border-color:var(--accent)}
#tt{position:absolute;opacity:0;width:1px;height:1px}
.tt{cursor:pointer;border:1px solid var(--line);background:var(--paper);border-radius:999px;padding:7px 14px;font-weight:600;font-size:14px}
#tt:focus-visible+.wrap .tt{outline:2px solid var(--accent);outline-offset:2px}
.days{display:flex;gap:6px;overflow-x:auto;padding:10px 2px 10px;scrollbar-width:thin}
.chip{flex:0 0 56px;font:inherit;color:inherit;background:var(--paper);border:1px solid var(--line);border-radius:10px;padding:6px 2px 5px;display:flex;flex-direction:column;align-items:center;cursor:pointer;min-height:58px}
.chip .dw{font-size:12px;color:var(--muted)}.chip .dn{font-size:19px;font-weight:700;line-height:1.1}
.chip .dt{font-size:11px;font-weight:600;color:var(--orange);min-height:13px}
.chip.hol .dt{color:var(--muted)}.chip.act{border-color:var(--orange)}
.chip.today{background:var(--sel);color:var(--sel-ink);border-color:var(--sel)}.chip.today .dw{color:inherit;opacity:.8}
.chip[aria-pressed=true]{outline:2px solid var(--orange);outline-offset:2px}
.chip:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.say{min-height:22px;font-size:14px;color:var(--muted);padding:0 2px 10px}
.todo{margin:14px 0;border:1.5px solid var(--orange);border-radius:10px;background:var(--paper);padding:10px 14px;display:flex;gap:12px}
.todo>span{color:var(--orange);font-weight:700;white-space:nowrap}
.todo ul{margin:0;padding:0;list-style:none}.todo li+li{margin-top:4px}
.money{background:var(--paper);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-bottom:6px}
.money .nums{display:flex;gap:18px;flex-wrap:wrap;align-items:baseline}
.money .nums b{font-size:18px}
.track{height:5px;background:var(--track);border-radius:3px;margin-top:8px;max-width:420px}
.track i{display:block;height:100%;border-radius:3px;background:var(--orange)}
.lede{font-size:13px;color:var(--muted);margin:8px 0 18px;max-width:80ch}
.check{border:1.5px solid var(--bad);border-radius:10px;background:var(--bad-bg);color:var(--bad);padding:10px 14px;margin:12px 0;font-size:14px}
.check ul{margin:4px 0 0;padding-left:18px}
h2{font-size:18px;margin:28px 0 10px}
.tbl{background:var(--paper);border:1px solid var(--line);border-radius:10px;overflow:hidden}
table.main{width:100%;border-collapse:collapse}
.main th{text-align:left;font-size:12px;font-weight:600;color:var(--muted);background:var(--paper2);padding:9px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
.main td{padding:11px 10px;border-bottom:1px solid var(--line);vertical-align:top;font-size:14px}
.main tr:last-child td{border-bottom:0}
.main tr.dim{opacity:.35}.main tr.hit{background:var(--tint)}
.c-name a{color:var(--ink);font-weight:700;text-decoration:none}.c-name a:hover{text-decoration:underline}
.c-verdict{min-width:200px}
.sub2{font-size:12px;color:var(--muted)}.muted{color:var(--muted)}
.warnline{font-size:12px;color:var(--warn);font-weight:600}
.yes{display:inline-block;background:#1f8a3b;color:#fff;font-weight:800;letter-spacing:.02em;padding:3px 9px;border-radius:999px;margin:0 6px 4px 0;font-size:.85em}.yes.maybe{background:#3f9a55}.applytoday{border:2px solid #1f8a3b;border-radius:14px;padding:12px 14px;margin:14px 0;background:var(--good-bg)}.applytoday>span{font-weight:800;color:var(--good);text-transform:uppercase;font-size:.8em;letter-spacing:.06em}.applytoday table{width:100%;border-collapse:collapse;margin-top:6px}.applytoday th,.applytoday td{text-align:left;padding:6px 8px;border-top:1px solid var(--line)}@media(max-width:700px){.applytoday thead{display:none}.applytoday td{display:block;border:0;padding:2px 0}.applytoday tr{display:block;border-top:1px solid var(--line);padding:8px 0}.applytoday td[data-l]::before{content:attr(data-l) ': ';color:var(--muted)}}.ok{color:var(--good)}.bad{color:var(--bad)}
.cat{color:var(--ink)}
.subgrid{display:grid;grid-template-columns:auto auto;gap:0 10px;font-size:13px}.subgrid span{color:var(--muted)}
.verdict{display:inline-block;font-weight:700;font-size:13px;border-radius:6px;padding:2px 8px;white-space:nowrap}
.v-apply{background:var(--good-bg);color:var(--good)}.v-cond{background:var(--mid-bg);color:var(--mid)}
.v-skip{background:var(--track);color:var(--muted)}.v-wait{background:var(--tint);color:var(--ink)}
.risk{font-weight:600;font-size:13px;padding:2px 8px;border-radius:6px;white-space:nowrap}
.r-low{background:var(--good-bg);color:var(--good)}.r-med{background:var(--mid-bg);color:var(--mid)}.r-high{background:var(--bad-bg);color:var(--bad)}
.amt{font-weight:700;margin-top:6px}
.checks{list-style:none;margin:6px 0 0;padding:0;font-size:12px}.checks li{display:flex;gap:6px}
.checks span{width:12px;font-weight:700;flex:none}.cok span{color:var(--good)}.cno span{color:var(--bad)}.cna{color:var(--muted)}
.cwarn{color:var(--warn)}
.cond{font-size:13px;margin-top:4px;max-width:46ch}
.card{background:var(--paper);border:1px solid var(--line);border-radius:10px;margin-bottom:12px;overflow:hidden;scroll-margin-top:190px}
.card header{display:flex;align-items:center;gap:10px;flex-wrap:wrap;background:var(--paper2);border-bottom:1px solid var(--line);padding:10px 14px}
.card h3{margin:0;font-size:16px}.card .when{color:var(--muted);font-size:13px;margin-left:auto}
.vid{font-size:13px;font-weight:600;border:1px solid var(--accent);border-radius:999px;padding:3px 10px;text-decoration:none}
.split{display:grid;grid-template-columns:1fr 1fr}
.split>div{padding:12px 14px}.split>div+div{border-left:1px solid var(--line)}
.split h4{margin:0 0 6px;font-size:13px;color:var(--muted);font-weight:600}.split h4.gap{margin-top:14px}
.split ul{margin:0;padding-left:18px}.split li+li{margin-top:5px}.split p{margin:8px 0 0}.split h4+p{margin-top:0}
.note{font-size:13px;background:var(--tint);border-radius:8px;padding:8px 10px}
.spark{position:relative;display:flex;align-items:flex-end;gap:4px;height:56px;border-bottom:1px solid var(--line);padding-right:34px}
.spark .bar{width:14px;height:var(--h);background:var(--orange);border-radius:2px 2px 0 0;opacity:.85}
.spark .bar.lo{background:var(--muted);opacity:.5}
.spark .gate{position:absolute;left:0;right:0;border-top:1px dashed var(--muted);height:0}
.spark .gate em{position:absolute;right:0;top:-8px;font-style:normal;font-size:11px;color:var(--muted);background:var(--paper);padding-left:4px}
.fin{border-collapse:collapse;font-size:12px;margin-top:10px}.fin td{padding:2px 8px 2px 0;white-space:nowrap}
.fin tr:first-child td{color:var(--muted)}
.small td,.small th{font-size:13px}
.calib td:not(:first-child),.calib th:not(:first-child){text-align:right}
.recap{font-size:15px;margin:0 0 12px;max-width:80ch}
.how{font-size:14px;max-width:80ch}.how li+li{margin-top:6px}
.err{border:1px solid var(--bad);color:var(--bad);border-radius:8px;padding:8px 12px;margin-top:12px;font-size:13px}
.two{display:grid;grid-template-columns:minmax(0,5fr) minmax(0,7fr);gap:14px;align-items:start}
footer{margin-top:30px;font-size:12px;color:var(--muted);max-width:80ch}
@media(max-width:900px){
 .top{position:static}
 .two{grid-template-columns:1fr}
 .main thead{display:none}
 .main,.main tbody,.main tr,.main td{display:block;width:100%}
 .main tr{border-bottom:1px solid var(--line);padding:8px 0 12px;display:flex;flex-direction:column}
 .main td{border:0;padding:4px 14px;display:grid;grid-template-columns:104px 1fr;gap:8px;order:2}
 .main td::before{content:attr(data-l);font-size:12px;color:var(--muted);padding-top:2px}
 .main td.c-name{display:block;padding-top:8px;order:0}.main td.c-name::before{content:none}
 .main td.c-verdict{order:1;padding-bottom:10px}
 .main td.c-verdict .v{background:var(--paper2);border-radius:8px;padding:8px 10px}
 .c-name a{font-size:17px}
 .split{grid-template-columns:1fr}.split>div+div{border-left:0;border-top:1px solid var(--line)}
 .card .when{margin-left:0}
 .calib td,.calib th{font-size:12px;padding:6px}
 .calib{display:table}.calib thead{display:table-header-group}.calib tbody{display:table-row-group}
 .calib tr{display:table-row}.calib td,.calib th{display:table-cell}.calib td::before{content:none}
}
@media(prefers-reduced-motion:no-preference){.main tr{transition:opacity .15s}}
"""

JS = """
const say=document.getElementById('say'),chips=[...document.querySelectorAll('.chip')],rows=[...document.querySelectorAll('#live tbody tr[data-days]')];
chips.forEach(c=>c.addEventListener('click',()=>{
 const on=c.getAttribute('aria-pressed')!=='true';
 chips.forEach(o=>o.setAttribute('aria-pressed','false'));
 if(on)c.setAttribute('aria-pressed','true');
 say.textContent=on?c.dataset.say:'Tap a day to see what happens and highlight its IPOs.';
 rows.forEach(r=>{const hit=on&&r.dataset.days.split(' ').includes(c.dataset.day);r.classList.toggle('hit',hit);r.classList.toggle('dim',on&&!hit)});
}));
"""

fetched = AUTO["fetched_at"]
rng = f"{days[0].strftime('%-d')}–{days[-1].strftime('%-d %B')}" if days[0].month == days[-1].month else \
    f"{days[0].strftime('%-d %b')} – {days[-1].strftime('%-d %b')}"
errors = AUTO.get("errors") or []
webcal = SITE.replace("https://", "webcal://") + "/ipo.ics"

today_rows = [i for i in live if applies_today(i)]
apply_today = ""
if today_rows:
    trs = "".join(
        f"<tr><td><b>{e(i['name'])}</b></td><td>{yes_badge(i)}</td><td data-l='Anant'>{e(i['anant'])}</td>"
        f"<td data-l='GMP'>{'—' if i['gmp_pct'] is None else '%.1f%%' % i['gmp_pct']}</td>"
        f"<td data-l='QIB'>{x((i.get('subscription') or {}).get('qib'))}</td><td data-l='Retail'>{x((i.get('subscription') or {}).get('retail'))}</td>"
        f"<td data-l='Bid'><b>{inr(i['block'])}</b> (1 lot)</td><td data-l='Deadline'>UPI mandate by 5 pm</td></tr>" for i in today_rows)
    apply_today = ('<div class="applytoday"><span>Apply today</span><table><thead><tr><th>IPO</th><th>Apply?</th><th>Anant</th>'
                   '<th>GMP</th><th>QIB</th><th>Retail</th><th>Bid</th><th>Deadline</th></tr></thead><tbody>' + trs + '</tbody></table></div>')

page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>IPO tracker · {rng}</title>
<meta name="description" content="Which IPOs to apply for, when, and with how much, for listing gains.">
<meta name="robots" content="noindex">
<style>{CSS}</style></head><body>
<input type="checkbox" id="tt" aria-label="Dark mode">
<div class="wrap">
<div class="top">
 <div class="bar1"><h1>IPO plan, {rng}</h1>
  <span class="pill">GMP gate <b>{BENCH}%</b></span><span class="pill">Capital <b>{inr(CAP)}</b></span>
  <a class="pill" href="#alerts">Phone alerts</a>
  <label class="tt" for="tt">Dark mode</label></div>
 <nav class="days" aria-label="Choose a day">{''.join(chips)}</nav>
 <div class="say" id="say" aria-live="polite">Tap a day to see what happens and highlight its IPOs.</div>
</div>

{apply_today}<div class="todo"><span>To do</span><ul>{''.join(f'<li>{t}</li>' for t in todo) or '<li>Nothing to do right now.</li>'}</ul></div>

<div class="money"><div class="nums"><span>Most money blocked at once <b>{inr(peak)}</b> of {inr(CAP)}</span>
 <span class="sub2">{('on ' + peak_day.strftime('%a %-d %b')) if peak_day else ''} · UPI blocks the amount until allotment, then releases what isn't allotted</span></div>
 <div class="track" role="img" aria-label="{peak_pct:.0f}% of capital"><i style="width:{peak_pct:.1f}%"></i></div></div>
<p class="lede">{e(NOTES.get('headline', ''))} Numbers updated {e(fetched.replace('T', ' ')[:16])} IST (every 30 minutes in market hours); Anant's calls checked at 11:15 and 2 pm on weekdays. {e(NOTES.get('benchmark_note', ''))}</p>
{('<div class="check"><b>Self-check found calls that break your rules:</b><ul>' + ''.join(f'<li>{e(p)}</li>' for p in problems) + '</ul></div>') if problems else ''}
{('<div class="err">Some sources failed on the last refresh: ' + e('; '.join(errors)) + '</div>') if errors else ''}

<h2>Open and upcoming</h2>
<div class="tbl"><table class="main" id="live"><thead><tr><th>IPO</th><th>Apply window</th><th>Allotment</th><th>Listing</th><th>Price and lot</th>
<th>GMP</th><th>Subscription</th><th>Allotment odds</th><th>Risk</th><th>Call (last day only)</th></tr></thead>
<tbody>{''.join(row(i) for i in live) or '<tr><td colspan=10 class="muted">No IPOs open or announced right now.</td></tr>'}</tbody></table></div>

{f'''<h2>Closed, waiting to list</h2><div class="tbl"><table class="main small"><thead><tr><th>IPO</th><th>Allotment</th><th>Listing</th><th>GMP</th><th>Subscribed</th><th>Listing day plan</th></tr></thead>
<tbody>{''.join(closed_row(i) for i in closed)}</tbody></table></div>''' if closed else ''}

<h2>Why each call</h2>
{''.join(why(i) for i in live)}

<h2 id="record">Track record</h2>
<p class="recap">{e(headline_stat)}</p>
<div class="two">
<div class="tbl"><table class="main small calib"><thead><tr><th>Group</th><th>IPOs</th><th>Avg open</th><th>Avg close</th><th>Closed up</th><th>Worst</th></tr></thead>
<tbody>{calib}</tbody></table></div>
<div class="tbl"><table class="main small"><thead><tr><th>IPO</th><th>Anant</th><th>GMP at close</th><th>Call</th><th>Listing open</th><th>Listing close</th><th>You</th></tr></thead>
<tbody>{rec_rows or '<tr><td colspan=7 class="muted">Nothing has listed yet.</td></tr>'}</tbody></table></div>
</div>
<p class="sub2">Gains are listing-day open and close against the issue price. Older rows come from Anant's ranking videos, with the call your rule would have made. Tell the tracker whether you applied and got shares, and the "You" column fills in.</p>

<h2 id="alerts">Phone alerts</h2>
<ul class="how">
<li><b>iPhone:</b> tap <a href="{webcal}">subscribe to the IPO calendar</a> and confirm. In Settings → Calendar → Accounts → Subscribed Calendars, turn off <i>Remove Alerts</i> so the reminders ring.</li>
<li><b>Android / Google Calendar:</b> on a laptop open Google Calendar → Other calendars → + → From URL, paste <code>{e(SITE)}/ipo.ics</code>. Then set a default notification for that calendar. Google ignores alarms inside the file and refreshes every few hours.</li>
<li>You get: "Apply" reminders at 11:30 am and 3 pm on the last day, a 2:15 pm check for "Apply if…" calls, allotment checks at 6 pm, and the listing-day plan at 9 am.</li>
</ul>

<h2>How the calls are made</h2>
<ul class="how">
<li><b>Calls happen on the last day only.</b> Before that an IPO is <b>Watching</b>, with a lean. On the last day the page shows the call <b>for now</b>, and it <b>locks at 2 pm</b>, leaving three hours before the 5 pm UPI cut-off.</li>
<li><b>Apply</b> needs all three: Anant's latest view is an A (or he hasn't covered it: silence counts as neutral, a B or C fails), the last-day GMP is at least {BENCH}% (the lowest source when they disagree by 5+ points), and institutions (QIB) have bid at least 1×. <b>Apply if…</b> (before 2 pm only) means rating and GMP pass and QIB hasn't reached 1× yet. Anything else is <b>Skip</b>.</li>
<li>A GMP more than 30% below its peak is flagged, not blocked. Replaying past IPOs, that check never changed a call: every IPO whose GMP collapsed had also fallen under {BENCH}%.</li>
<li><b>Allotment odds</b> are for one retail application. Every retail applicant enters a lottery for 1 lot, so the odds are retail lots on offer ÷ applications. Extra lots only help when lots outnumber applicants.</li>
<li><b>GMP</b> shows InvestorGain first (IPOWatch's day-by-day page for that IPO takes over when InvestorGain is down or empty), then IPOWatch and Anant's own Telegram figure when he posts one. A gap of 5 points or more between sources is flagged, since grey-market quotes can be inflated.</li>
<li><b>Risk</b> is the chance of losing money on listing day. Low: GMP 25%+ and steady, profitable, strong demand. Medium: GMP 15–25% or volatile, or one notable red flag. High: GMP under 15% or falling, loss-making, weak institutions, or SME.</li>
<li><b>Money</b> assumes one PAN, 1 lot per IPO, and {inr(CAP)} total. SME IPOs only appear when Anant rates them A{(' (left out now: ' + e(', '.join(skipped_sme)) + ')') if skipped_sme else ''}.</li>
<li><b>Selling</b> follows Anant: for a strong listing (around 25%+), use the Rule of 15. Note the low of the first 15 minutes and exit when it breaks. For an average one, sell in the pre-open.</li>
</ul>
<footer>GMP is unofficial grey-market data and can change fast. This page is a personal tracker, not investment advice. <a href="https://github.com/rohan-patnaik/ipo-tracker">Source</a></footer>
</div>
<script>{JS}</script>
</body></html>"""


# every in-page link must land somewhere
_ids = set(re.findall(r'id="([^"]+)"', page))
for _a in sorted(set(re.findall(r'href="#([^"]+)"', page)) - _ids):
    problems.append(f"Broken in-page link #{_a}.")

out = ROOT / "site"
out.mkdir(exist_ok=True)
(out / "index.html").write_text(page)
(out / "ipo.ics").write_text("\r\n".join(fold(line) for line in ics) + "\r\n")
(out / "lint.json").write_text(json.dumps(problems, indent=1, ensure_ascii=False))

# plain-text summary for the thread post
lines = [f"IPO tracker, numbers as of {fetched}", ""]
for i in live:
    s = i.get("subscription") or {}
    gp = "—" if i["gmp_pct"] is None else "%.1f%%" % i["gmp_pct"]
    lines.append(f"- {i['name']}: {VERDICT.get(i['verdict'], (i['verdict'],))[0]} | last day {short(i.get('close'))} | GMP {gp} | "
                 f"retail {x(s.get('retail'))} | odds {odds(i)[0]} | Anant {i['anant']} | risk {i['risk']} | "
                 f"{inr(i['block']) if i['block'] else ''} {i['condition']}")
if problems:
    lines += ["", "SELF-CHECK PROBLEMS:"] + [f"- {p}" for p in problems]
(out / "summary.md").write_text("\n".join(lines))
print(out / "index.html", f"| {len(cal) and sum(1 for l in cal if l == 'BEGIN:VEVENT')} calendar events | {len(problems)} self-check problems")
for p in problems:
    print("  !", p)
if "--strict" in sys.argv and problems:
    sys.exit(2)
