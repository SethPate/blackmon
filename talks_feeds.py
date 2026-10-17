#!/usr/bin/env python3
"""Readings, talks and gallery openings, each source read from its own feed. Stdlib only. talks.py places and sorts them.

Each source function returns a list of dicts:
  {venue, title, start (naive America/New_York datetime), link, notes, address}
Run: python3 talks.py 2026-10-17
"""
import datetime as dt
import html
import json
import re
import sys
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124 Safari/537.36")
# McNally Jackson / Word (IndieCommerce on Pantheon) 403 "update your browser"
# for Chrome/124 specifically; any newer Chrome token (or plain "Mozilla/5.0") works.
UA_NEW = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")


def get(url, ua=UA, headers=None, data=None, timeout=40):
    h = {"User-Agent": ua}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def getjson(url, **kw):
    return json.loads(get(url, **kw))


def utc_to_ny(s):
    """'2026-10-22T23:00:00Z' or '+00:00' -> naive NY datetime."""
    d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d.astimezone(NY).replace(tzinfo=None)


def strip(s):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s or "")).split())


def ev(venue, title, start, link, notes="", address=""):
    return dict(venue=venue, title=strip(title), start=start, link=link,
                notes=notes, address=address)


def window(days):
    now = dt.datetime.now(NY).replace(tzinfo=None)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + dt.timedelta(days=days + 1)


# ---------------------------------------------------------------- galleries
def artforum_artguide(days=7):
    """Artforum artguide (WordPress REST, public). Gallery openings with reception
    date+time; venue address via a 2nd batched call. ~25-30 NYC openings/week."""
    lo, hi = window(days)
    after = (lo - dt.timedelta(days=90)).strftime("%Y-%m-%dT00:00:00")
    F = ("id,date,link,title,meta.reception_date,meta.reception_start_time,"
         "meta.reception_end_time,meta.location_slug,meta.venue_name,meta.venue_id,"
         "meta.type,meta.start_date,meta.end_date,meta.artists,meta.neighborhood_name")
    rows, page = [], 1
    while page < 40:
        u = ("https://artguide.artforum.com/wp-json/wp/v2/ag-exhibition-event"
             f"?per_page=100&page={page}&after={after}&orderby=date&order=desc&_fields={F}")
        try:
            d = getjson(u)
        except urllib.error.HTTPError as e:   # 400 past last page
            if e.code == 400:
                break
            raise
        if not d:
            break
        rows += d
        page += 1
    picks = []
    for r in rows:
        m = r["meta"]
        if m.get("location_slug") != "new-york" or not m.get("reception_date"):
            continue
        # formats seen: '2026-10-21', '2026-10-21 00:00:00', '2026-10-21T04:00:00.000Z' (NY midnight)
        rdate = m["reception_date"][:10]
        t = (m.get("reception_start_time") or "00:00")
        t = t[11:16] if len(t) > 5 else t          # '2026-10-21 18:00:00' -> '18:00'
        start = dt.datetime.fromisoformat(f"{rdate}T{t}")
        if lo <= start < hi:
            picks.append((r, start))
    vids = sorted({str(r["meta"]["venue_id"]) for r, _ in picks})
    addr = {}
    for i in range(0, len(vids), 100):
        u = ("https://artguide.artforum.com/wp-json/wp/v2/ag-venue?per_page=100&include="
             + ",".join(vids[i:i + 100])
             + "&_fields=id,meta.address_line_1,meta.address_line_2,meta.locality,meta.postal_code")
        for v in getjson(u):
            vm = v["meta"]
            addr[v["id"]] = ", ".join(x for x in (vm.get("address_line_1"), vm.get("address_line_2"),
                                                  vm.get("locality"), vm.get("postal_code")) if x)
    out = []
    for r, start in picks:
        m = r["meta"]
        kind = "opening reception" if m.get("type") == "exhibition" else "gallery event"
        notes = f"{kind}"
        if m.get("reception_end_time"):
            notes += f" until {m['reception_end_time'][-8:-3] if len(m['reception_end_time']) > 5 else m['reception_end_time']}"
        if m.get("artists"):
            notes += f"; artists: {m['artists']}"
        if m.get("start_date"):
            notes += f"; on view {m['start_date']}..{m.get('end_date', '')}"
        if not m.get("reception_start_time"):
            notes += "; time not given"
        out.append(ev(html.unescape(m["venue_name"]), r["title"]["rendered"], start, r["link"], notes,
                      addr.get(m["venue_id"], "")))
    return out


def artsy(days=7):
    """Artsy public GraphQL (metaphysics), no token. Opening-reception events attached
    to NYC shows. Fewer than artguide (~5-10/wk) but different galleries."""
    lo, hi = window(days)
    Q = """query($after:String){ city(slug:"new-york-ny-usa"){ showsConnection(first:50, after:$after,
      status:RUNNING_AND_UPCOMING, sort:START_AT_DESC){ pageInfo{hasNextPage endCursor}
      edges{ node{ name href startAt endAt events{ eventType title startAt endAt }
      partner{ ... on Partner{ name } } location{ address address2 city postalCode } } } } } }"""
    out, after = [], None
    for _ in range(10):
        body = json.dumps({"query": Q, "variables": {"after": after}}).encode()
        d = json.loads(get("https://metaphysics-production.artsy.net/v2", data=body,
                           headers={"Content-Type": "application/json"}))
        c = d["data"]["city"]["showsConnection"]
        for e in c["edges"]:
            s = e["node"]
            for x in s.get("events") or []:
                if not x.get("startAt"):
                    continue
                start = utc_to_ny(x["startAt"])
                if lo <= start < hi:
                    loc = s.get("location") or {}
                    a = ", ".join(v for v in (loc.get("address"), loc.get("address2"),
                                              loc.get("city"), loc.get("postalCode")) if v)
                    out.append(ev((s.get("partner") or {}).get("name", ""), s["name"], start,
                                  "https://www.artsy.net" + s["href"],
                                  f"{x.get('eventType')} until {utc_to_ny(x['endAt']).strftime('%H:%M') if x.get('endAt') else '?'}",
                                  a))
        if not c["pageInfo"]["hasNextPage"]:
            break
        after = c["pageInfo"]["endCursor"]
    return out


# ---------------------------------------------------------------- BookManager
BM_API = "https://api.bookmanager.com/customer/"


def _bm_post(ep, d):
    return json.loads(get(BM_API + ep, data=urllib.parse.urlencode(d).encode()))


def bookmanager(san, site, venue, days=7):
    """BookManager storefront API (same calls the site's React app makes):
    store/getSettings -> session/get (anonymous session) -> event/v2/list (or v1 getList)."""
    lo, hi = window(days)
    s = _bm_post("store/getSettings", {"webstore_name": san, "uuid": "blackmon"})
    sid = s["store_info"]["id"]
    si = s["store_info"]
    store_addr = f"{si.get('address', '')}, {si.get('city', '')}"
    sess = _bm_post("session/get", {"store_id": sid, "uuid": "blackmon", "session_id": ""})["session_id"]
    base = {"store_id": sid, "uuid": "blackmon", "session_id": sess}
    out = []
    if s.get("using_events_v2"):
        d = _bm_post("event/v2/list", dict(base, start_date=lo.strftime("%Y%m%d"),
                                           end_date=hi.strftime("%Y%m%d"), limit=100, offset=0))
        for r in d.get("rows", []):
            if r.get("all_day") or not r.get("start_time"):
                start = dt.datetime.strptime(r["date"], "%Y%m%d")
            else:
                start = dt.datetime.strptime(r["date"] + r["start_time"], "%Y%m%d%H:%M:%S")
            if not lo <= start < hi:
                continue
            cat = (r.get("category") or {}).get("name", "")
            out.append(ev(venue, r["title"], start, f"{site}/events/{r['id']}",
                          f"category: {cat}; location: {r.get('location_text', '')}",
                          r.get("location_text") or store_addr))
    else:
        d = _bm_post("event/getList", dict(base, **{"from": lo.strftime("%Y%m%d")}))
        for r in d.get("rows", []):
            # 'from' is epoch encoded so that UTC-7h == local wall time (site JS does utcOffset(-7))
            start = (dt.datetime(1970, 1, 1) + dt.timedelta(seconds=r["from"] - 7 * 3600)).replace(second=0)
            if not lo <= start < hi:
                continue
            info = r.get("info", {})
            authors = sorted({a["name"] for b in info.get("book", []) for a in b.get("authors", [])})
            out.append(ev(venue, info.get("name", ""), start, f"{site}/events/{r['id']}",
                          "authors: " + ", ".join(authors) if authors else "", store_addr))
    return out


def books_are_magic(days=7):
    return bookmanager("9903658", "https://www.booksaremagic.net", "Books Are Magic", days)


def community_bookstore(days=7):
    return bookmanager("1210467", "https://www.communitybookstore.net", "Community Bookstore", days)


def astoria_bookshop(days=7):
    return bookmanager("920590x", "https://www.astoriabookshop.com", "Astoria Bookshop", days)


# ---------------------------------------------------------------- Eventbrite
def eventbrite_org(org_id, venue, days=7):
    """Eventbrite v3 organizer events; answers anonymously (no token) on www.eventbrite.com."""
    lo, hi = window(days)
    out, page = [], 1
    while True:
        u = (f"https://www.eventbrite.com/api/v3/organizers/{org_id}/events/"
             f"?status=live&order_by=start_asc&expand=venue&page={page}")
        d = getjson(u)
        for e in d.get("events", []):
            start = dt.datetime.fromisoformat(e["start"]["local"])
            if not lo <= start < hi:
                continue
            v = e.get("venue") or {}
            a = (v.get("address") or {}).get("localized_address_display", "")
            notes = ("online" if e.get("online_event") else f"at {v.get('name', '')}") + \
                    ("; free" if e.get("is_free") else "")
            out.append(ev(venue, e["name"]["text"], start, e["url"], notes, a))
        if not d.get("pagination", {}).get("has_more_items"):
            break
        page += 1
    return out


def greenlight(days=7):
    return eventbrite_org("13064382976", "Greenlight Bookstore", days)


def strand(days=7):
    return eventbrite_org("30058841244", "Strand Book Store", days)


def twisted_spine(days=7):  # bonus: Williamsburg genre bookstore with many launches
    return eventbrite_org("114781508361", "The Twisted Spine", days)


# ---------------------------------------------------------------- IndieCommerce HTML
def indiecommerce(site, venue, days=7):
    """IndieCommerce (Drupal) /events list page: server-rendered <article class="event-list">.
    Lists the current month; no JSON/iCal route."""
    lo, hi = window(days)
    t = get(site + "/events", ua=UA_NEW)
    out = []
    for art in re.findall(r'<article id="event-\d+" class="event-list">(.*?)</article>', t, re.S):
        m = re.search(r'event-list__title">\s*<a href="([^"]+)"[^>]*>(.*?)</a>', art, re.S)
        dm = re.search(r'Date:\s*</span>\s*\w+,\s*(\d+/\d+/\d{4})', art)
        tm = re.search(r'Time:\s*</span>\s*([0-9:]+\s*[ap]m)', art, re.I)
        if not (m and dm):
            continue
        d = dt.datetime.strptime(dm.group(1), "%m/%d/%Y")
        if tm:
            tt = tm.group(1).replace(" ", "").lower()
            fmt = "%I:%M%p" if ":" in tt else "%I%p"
            tv = dt.datetime.strptime(tt, fmt)
            d = d.replace(hour=tv.hour, minute=tv.minute)
        if not lo <= d < hi:
            continue
        place = re.search(r'<p class="address"[^>]*>(.*?)</p>', art, re.S)
        a = strip(place.group(1).replace("<br>", ", ")) if place else ""
        a = a.replace(" United States", "").strip(", ")
        out.append(ev(venue, m.group(2), d, site + m.group(1), "", a))
    return out


def mcnally_jackson(days=7):
    return indiecommerce("https://mcnallyjackson.com", "McNally Jackson", days)


# ---------------------------------------------------------------- iCal (WP Events Manager)
def _ics_events(text):
    text = re.sub(r"\r?\n[ \t]", "", text)  # unfold
    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S):
        f = {}
        for line in block.strip().splitlines():
            k, _, v = line.partition(":")
            f.setdefault(k.split(";")[0], (k, v))
        yield f


def _ics_val(v):
    return v.replace("\\,", ",").replace("\\;", ";").replace("\\n", " ").strip()


def events_manager_ics(url, venue, default_addr, days=7):
    lo, hi = window(days)
    out = []
    for f in _ics_events(get(url)):
        k, v = f.get("DTSTART", ("", ""))
        if not v:
            continue
        if v.endswith("Z"):
            start = utc_to_ny(dt.datetime.strptime(v, "%Y%m%dT%H%M%SZ").isoformat() + "Z")
        elif "T" in v:
            start = dt.datetime.strptime(v, "%Y%m%dT%H%M%S")  # TZID=America/New_York
        else:
            start = dt.datetime.strptime(v, "%Y%m%d")
        if not lo <= start < hi:
            continue
        loc = _ics_val(f.get("LOCATION", ("", ""))[1])
        out.append(ev(venue, _ics_val(f["SUMMARY"][1]), start, f.get("URL", ("", ""))[1],
                      "", html.unescape(loc) or default_addr))
    return out


def powerhouse_arena(days=7):
    return events_manager_ics("https://powerhousearena.com/events.ics", "POWERHOUSE Arena",
                              "28 Adams St, Brooklyn, NY 11201", days)


# ---------------------------------------------------------------- Poetry Project
def poetry_project(days=7):
    lo, hi = window(days)
    t = get("https://www.poetryproject.org/events")
    out = []
    for art in re.findall(r'<article class="upcomingEvent[^"]*"[^>]*>(.*?)</article>', t, re.S):
        a = re.search(r'<a href="([^"]+)"', art)
        h2 = re.search(r"<h2>(.*?)</h2>", art, re.S)
        tm = re.search(r'<time datetime="([^"]+)"', art)
        if not (a and h2 and tm):
            continue
        start = dt.datetime.fromisoformat(tm.group(1)).astimezone(NY).replace(tzinfo=None)
        if not lo <= start < hi:
            continue
        cat = re.search(r'class="category">(.*?)<', art)
        loc = re.search(r'class="location">(.*?)<', art)
        price = re.search(r'class="price">:?\s*(.*?)<', art)
        locs = strip(loc.group(1)) if loc else ""
        addr = "131 E 10th St, New York, NY 10003" if "Mark" in locs else locs
        out.append(ev("The Poetry Project", h2.group(1), start, a.group(1),
                      f"{strip(cat.group(1)) if cat else ''}; {locs}; {price.group(1) if price else ''}",
                      addr))
    return out


# ---------------------------------------------------------------- Brooklyn Public Library
def brooklyn_public_library(days=7, tags="author talks||BPL Presents"):
    """discover.bklynlibrary.org Solr proxy. Needs a Referer header (else {"error":"access denied"})."""
    lo, hi = window(days)
    out, pg = [], 1
    while pg < 10:
        q = urllib.parse.urlencode({"event": "true", "eventtags": tags,
                                    "inpersonevent": "true", "pagination": pg})
        d = getjson("https://discover.bklynlibrary.org/api/search/v2.php?" + q,
                    headers={"Referer": "https://discover.bklynlibrary.org/"})
        groups = d["grouped"]["ss_grouping"]["groups"]
        for g in groups:
            e = g["doclist"]["docs"][0]
            start = utc_to_ny(e["ds_event_start_date"])
            if not lo <= start < hi or e.get("is_event_canceled") == 1:
                continue
            alias = re.search(r'"alias":"([^"]+)"', e.get("ss_node_json", ""))
            link = "https://www.bklynlibrary.org" + alias.group(1).replace("\\/", "/") if alias else ""
            loc = e.get("ss_event_location", "")
            addr = ("10 Grand Army Plaza, Brooklyn, NY 11238" if loc.startswith("Central Library")
                    else "128 Pierrepont St, Brooklyn, NY 11201" if "Brooklyn History" in loc else loc)
            out.append(ev("Brooklyn Public Library", e["ts_title"], start, link,
                          f"{loc}; tags: {e.get('tm_event_tags', '')}", addr))
        if len(groups) < 20:
            break
        pg += 1
    return out


# ---------------------------------------------------------------- Cooper Union
def _cooper_time(txt):
    """'6:30 - 8:30PM' / '11:00AM - 1:00PM' / '7PM' -> {hour, minute} of the start."""
    parts = [p.strip() for p in txt.split("-")]
    rx = re.compile(r"(\d{1,2})(?::(\d\d))?\s*([AP]M)?", re.I)
    m1 = rx.match(parts[0])
    m2 = rx.match(parts[-1]) if len(parts) > 1 else m1
    if not m1:
        return {}
    ampm = (m1.group(3) or (m2.group(3) if m2 else None) or "PM").upper()
    h = int(m1.group(1)) % 12 + (12 if ampm == "PM" else 0)
    if not m1.group(3) and m2 and m2.group(3):
        h2 = int(m2.group(1)) % 12 + (12 if m2.group(3).upper() == "PM" else 0)
        if h > h2:          # "11:00 - 1:00PM" -> start is 11 AM
            h -= 12
    return {"hour": h, "minute": int(m1.group(2) or 0)}


def cooper_union(days=7):
    lo, hi = window(days)
    out = []
    months = {lo.strftime("%Y/%m"), (hi - dt.timedelta(days=1)).strftime("%Y/%m")}
    for ym in sorted(months):
        t = get(f"https://cooper.edu/events-and-exhibitions/events/{ym}")
        for sec in re.split(r'<section class="day">', t)[1:]:
            dm = re.search(r'<div id="(\d\d)-(\d\d)-(\d{4})" class="title">', sec)
            if not dm:
                continue
            day = dt.datetime(int(dm.group(3)), int(dm.group(1)), int(dm.group(2)))
            for li in re.findall(r"<li class=[^>]*>(.*?)</li>", sec, re.S):
                a = re.search(r'<h3>\s*<a href="([^"]+)"[^>]*>(.*?)</a>', li, re.S)
                tm = re.search(r"<time>(.*?)</time>", li, re.S)
                if not a:
                    continue
                start = day
                if tm:
                    start = day.replace(**_cooper_time(strip(tm.group(1))))
                if lo <= start < hi:
                    out.append(ev("The Cooper Union", a.group(2), start, "https://cooper.edu" + a.group(1),
                                  strip(tm.group(1)) if tm else "",
                                  "7 E 7th St (Foundation Bldg), New York, NY 10003"))
    return out
