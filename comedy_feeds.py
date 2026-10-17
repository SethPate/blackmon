#!/usr/bin/env python3
"""Comedy venues, each read from its own site or ticketing feed. Stdlib only. comedy.py places and sorts what these return.

Each fetch_<venue>(days=7) returns a list of dicts:
    {venue, title, start (naive America/New_York datetime), link, notes}
Window = [today 00:00 NY, today 00:00 + days).  Run: python3 comedy_feeds.py [days]
No browser, login, captcha or lifted credentials: plain GET/POST with a desktop UA.
"""
import datetime as dt
import html
import json
import re
import sys
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

NY = ZoneInfo('America/New_York')
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124 Safari/537.36')


def get(url, headers=None, data=None, json_body=None, timeout=30):
    """GET, or POST when data (dict -> form-encoded, str/bytes raw) or json_body is given."""
    h = {'User-Agent': UA, 'Accept': '*/*', 'Accept-Language': 'en-US,en;q=0.9'}
    if json_body is not None:
        data = json.dumps(json_body).encode()
        h['Content-Type'] = 'application/json'
    elif isinstance(data, dict):
        data = urllib.parse.urlencode(data).encode()
    elif isinstance(data, str):
        data = data.encode()
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', 'replace')


def _now():
    return dt.datetime.now(NY).replace(tzinfo=None)


def _window(days):
    start = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + dt.timedelta(days=days)


def _iso_to_ny(s):
    d = dt.datetime.fromisoformat(s)
    if d.tzinfo:
        d = d.astimezone(NY).replace(tzinfo=None)
    return d


def _to_ny_naive(iso):
    """ISO string with offset (or Z) -> naive NY time. Naive input returned as-is."""
    iso = iso.replace('Z', '+00:00')
    d = dt.datetime.fromisoformat(iso)
    if d.tzinfo is None:
        return d
    try:
        from zoneinfo import ZoneInfo
        return d.astimezone(ZoneInfo('America/New_York')).replace(tzinfo=None)
    except Exception:
        return d.replace(tzinfo=None)  # fallback: wall time as given


def _strip(s):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', s or ''))).strip()


def _ldjson(page):
    out = []
    for b in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', page, re.S):
        try:
            d = json.loads(b)
        except ValueError:
            continue
        out.extend(d if isinstance(d, list) else [d])
    return out


# ---------------------------------------------------------------- Comedy Cellar
def fetch_comedy_cellar(days=7):
    """POST https://www.comedycellar.com/lineup/api/  one call per date.
    Rooms: MacDougal Street, Village Underground, Fat Black Pussycat (Lounge/Bar).
    showid in reservation link == NY wall-clock time encoded as a UTC epoch."""
    lo, hi = _window(days)
    out = []
    for i in range(days):
        day = (lo + dt.timedelta(days=i)).strftime('%Y-%m-%d')
        body = {'action': 'cc_get_shows',
                'json': json.dumps({'date': day, 'venue': 'newyork', 'type': 'lineup'})}
        d = json.loads(get('https://www.comedycellar.com/lineup/api/', data=body,
                           headers={'Referer': 'https://www.comedycellar.com/new-york-line-up/'}))
        h = (d.get('show') or {}).get('html') or ''
        for blk in re.split(r'<div class="set-header">', h)[1:]:
            room = re.search(r'<span class="title">([^<]+)', blk)
            sid = re.search(r'showid=(\d+)', blk)
            tm = re.search(r'<span class="bold">([^<]+)<', blk)
            if not (room and sid):
                continue
            start = dt.datetime(1970, 1, 1) + dt.timedelta(seconds=int(sid.group(1)))
            names = [html.unescape(n) for n in re.findall(r'<span class="name">([^<]+)', blk)]
            room = html.unescape(room.group(1)).strip()
            out.append({'venue': 'Comedy Cellar - ' + room,
                        'title': 'Comedy Cellar: ' + room,
                        'start': start,
                        'link': 'https://www.comedycellar.com/reservations-newyork/?showid=' + sid.group(1),
                        'notes': 'Lineup: ' + ', '.join(names) if names else (tm.group(1) if tm else '')})
    return [e for e in out if lo <= e['start'] < hi]


# ---------------------------------------------------------------- Caveat
def fetch_caveat(days=7):
    """GET https://caveat.nyc/api/events/listings (public, no auth)."""
    lo, hi = _window(days)
    d = json.loads(get('https://caveat.nyc/api/events/listings'))
    out = []
    for r in d.get('records', []):
        f = r.get('fields', {})
        iso = f.get('google_start_time') or f.get('Event start date and time')
        if not iso:
            continue
        start = _to_ny_naive(iso)
        if not (lo <= start < hi):
            continue
        link = f.get('Ticket URL') or f.get('Stellar URL') or (
            'https://caveat.nyc/events/' + f['slug'] if f.get('slug') else 'https://caveat.nyc/')
        out.append({'venue': 'Caveat', 'title': f.get('Event', '').strip(), 'start': start,
                    'link': link,
                    'notes': '; '.join(x for x in [f.get('Tags') or '', f.get('Short description') or ''] if x)})
    return sorted(out, key=lambda e: e['start'])


# ---------------------------------------------------------------- Eventbrite helper
def _eventbrite_by_ids(ids):
    """Public Eventbrite destination endpoint (no token). <=50 ids per call."""
    out = []
    ids = list(dict.fromkeys(ids))
    for i in range(0, len(ids), 40):
        url = ('https://www.eventbrite.com/api/v3/destination/events/?event_ids='
               + ','.join(ids[i:i + 40]) + '&page_size=50')
        out.extend(json.loads(get(url)).get('events', []))
    return out


# ---------------------------------------------------------------- Union Hall
def fetch_union_hall(days=7):
    """GET https://unionhallny.com/calendar (Spacecraft site, server-rendered, has
    Eventbrite ids + lineup names but no times) -> Eventbrite destination API for times."""
    lo, hi = _window(days)
    page = get('https://unionhallny.com/calendar')
    lineup = {}
    for item in page.split('class="item eventColl-item')[1:]:
        m = re.search(r'data-purchase-id="(\d+)"', item)
        if not m:
            continue
        a = re.search(r'eventColl-artistNames[^>]*>(.*?)</', item, re.S)
        lineup.setdefault(m.group(1), _strip(a.group(1)) if a else '')
    out = []
    for e in _eventbrite_by_ids(list(lineup)):
        start = dt.datetime.fromisoformat(e['start_date'] + 'T' + e['start_time'])  # local NY
        if not (lo <= start < hi) or e.get('is_cancelled'):
            continue
        out.append({'venue': 'Union Hall', 'title': e['name'].strip(), 'start': start,
                    'link': e['url'],
                    'notes': ('Lineup: ' + lineup[e['id']]) if lineup.get(e['id']) else (e.get('summary') or '')})
    return sorted(out, key=lambda e: e['start'])


# ---------------------------------------------------------------- Littlefield
def fetch_littlefield(days=7):
    """GET https://littlefieldnyc.com/all-shows/ (WP + 'widget for eventbrite' plugin;
    links /event/?wfea_eb_id=<eventbrite id>) -> Eventbrite destination API."""
    lo, hi = _window(days)
    page = get('https://littlefieldnyc.com/all-shows/')
    ids = list(dict.fromkeys(re.findall(r'wfea_eb_id=(\d+)', page)))
    out = []
    for e in _eventbrite_by_ids(ids[:80]):
        start = dt.datetime.fromisoformat(e['start_date'] + 'T' + e['start_time'])
        if not (lo <= start < hi) or e.get('is_cancelled'):
            continue
        out.append({'venue': 'Littlefield', 'title': e['name'].strip(), 'start': start,
                    'link': e['url'], 'notes': (e.get('summary') or '')[:200]})
    return sorted(out, key=lambda e: e['start'])


# ---------------------------------------------------------------- The Bell House
def fetch_bell_house(days=7):
    """GET https://www.thebellhouseny.com/  JSON-LD MusicEvent blocks (Ticketmaster links).
    startDate is naive local time."""
    lo, hi = _window(days)
    out = []
    for it in _ldjson(get('https://www.thebellhouseny.com/')):
        if not str(it.get('@type', '')).endswith('Event') or not it.get('startDate'):
            continue
        start = _to_ny_naive(it['startDate'])
        if not (lo <= start < hi):
            continue
        out.append({'venue': 'The Bell House', 'title': html.unescape(it.get('name', '')).strip(),
                    'start': start, 'link': it.get('url') or 'https://www.thebellhouseny.com/',
                    'notes': 'Mixed venue (comedy/music/talk); ticketmaster'})
    return sorted(out, key=lambda e: e['start'])


# ---------------------------------------------------------------- Gotham
def fetch_gotham(days=7):
    """GET https://gothamcomedyclub.com/  server-rendered .gsc-schedule-row list (~10 weeks)."""
    lo, hi = _window(days)
    page = get('https://gothamcomedyclub.com/')
    out = []
    for r in page.split('class="gsc-schedule-row"')[1:]:
        day = re.search(r'gsc-schedule-date day">\s*(\d+)', r)
        my = re.findall(r'<div class="gsc-schedule-date">([^<]+)</div>', r)
        tm = re.search(r'gsc-schedule-time-col">\s*<div class="gsc-schedule-time">([^<]+)', r)
        a = re.search(r'gsc-schedule-title"><a href="([^"]+)">([^<]+)', r)
        if not (day and len(my) >= 2 and tm and a):
            continue
        start = dt.datetime.strptime('%s %s %s %s' % (day.group(1), my[0].strip(), my[1].strip(),
                                                      tm.group(1).strip()), '%d %b %Y %I:%M %p')
        if lo <= start < hi:
            out.append({'venue': 'Gotham Comedy Club', 'title': html.unescape(a.group(2)).strip(),
                        'start': start, 'link': a.group(1), 'notes': ''})
    return out


# ---------------------------------------------------------------- New York Comedy Club
def fetch_new_york_comedy_club(days=7):
    """GET https://newyorkcomedyclub.com/calendar/YYYY-MM  one JSON-LD array of ComedyEvent
    (all 3 NYC rooms + performer[] lineup). location.name distinguishes rooms;
    Stamford is on a separate subdomain and not included."""
    lo, hi = _window(days)
    months = sorted({(lo + dt.timedelta(days=i)).strftime('%Y-%m') for i in range(days)})
    out, seen = [], set()
    for m in months:
        for it in _ldjson(get('https://newyorkcomedyclub.com/calendar/' + m)):
            if it.get('@type') != 'ComedyEvent' or not it.get('startDate'):
                continue
            start = _to_ny_naive(it['startDate'])
            key = (it.get('url'), start)
            if not (lo <= start < hi) or key in seen:
                continue
            seen.add(key)
            room = (it.get('location') or {}).get('name', 'New York Comedy Club')
            addr = ((it.get('location') or {}).get('address') or {}).get('streetAddress', '').strip()
            names = [p.get('name') for p in it.get('performer') or [] if isinstance(p, dict)]
            out.append({'venue': room + (' (%s)' % addr if addr else ''),
                        'title': html.unescape(it.get('name', '')).strip(), 'start': start,
                        'link': it.get('url'),
                        'notes': 'Lineup: ' + ', '.join(names) if names else ''})
    return sorted(out, key=lambda e: e['start'])


# ---------------------------------------------------------------- not fetchable
def fetch_ucb(days=7):
    """ucbcomedy.com: every path except robots.txt returns Cloudflare managed
    challenge (403, cf-mitigated: challenge). No third-party ticketing (self-hosted
    WooCommerce/Tickera). Not fetchable without a browser."""
    return []


def fetch_the_stand(days=7):
    """thestandnyc.com: Cloudflare managed challenge on all paths. Not fetchable."""
    return []


def _clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _months(days):
    lo, hi = _window(days)
    out, d = [], lo.replace(day=1)
    while d < hi:
        out.append(d.strftime("%Y-%m"))
        d = (d + dt.timedelta(days=32)).replace(day=1)
    return out


def _jsonld_events(page):
    ev = []
    for m in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        try:
            d = json.loads(m)
        except ValueError:
            continue
        items = d if isinstance(d, list) else d.get("@graph", [d])
        ev += [x for x in items if isinstance(x, dict) and "Event" in str(x.get("@type", ""))]
    return ev


# --- Shared: the "img/venues" white-label club platform (Eastville, Grisly Pear, Rodney's).
# Server-rendered month calendar at /calendar/YYYY-MM with a JSON-LD ComedyEvent array.
def _club_calendar(base, venue, days):
    lo, hi = _window(days)
    seen, out = set(), []
    for ym in _months(days):
        for e in _jsonld_events(get(f"{base}/calendar/{ym}")):
            start = _iso_to_ny(e["startDate"])
            link = e.get("url") or (e.get("offers") or {}).get("url")
            if not (lo <= start < hi) or (link, start) in seen:
                continue
            seen.add((link, start))
            addr = ((e.get("location") or {}).get("address") or {}).get("streetAddress", "")
            desc = _clean(e.get("description"))
            out.append({"venue": venue, "title": _clean(e.get("name")), "start": start,
                        "link": link, "notes": f"{addr} | {desc[:200]}".strip(" |")})
    return sorted(out, key=lambda x: x["start"])


def fetch_eastville(days=7):
    # 487 Atlantic Ave, Brooklyn. Title is usually the lineup itself.
    return _club_calendar("https://www.eastvillecomedy.com", "Eastville Comedy Club", days)


def fetch_grisly_pear(days=7):
    # Two rooms: 107 MacDougal St (Greenwich Village) and 243 W 54th St (Midtown); see notes.
    return _club_calendar("https://www.grislypearstandup.com", "The Grisly Pear", days)


def fetch_rodneys(days=7):
    # 1118 First Ave (UES). rodneycomedy.com redirects here.
    return _club_calendar("https://www.rodneysnewyorkcomedyclub.com", "Rodney's Comedy Club", days)


# --- Comic Strip Live: WordPress, server-rendered /schedule. "<h4 class="date-time">Friday 16 October 10/16/26 8:00 pm"
# The mm/dd/yy part is sometimes stale (copied posts), so use "Weekday DD Month" + time, infer year.
def fetch_comic_strip(days=7):
    lo, hi = _window(days)
    page = get("https://comicstriplive.com/schedule")
    out = []
    for blk in page.split('class="post-block"')[1:]:
        t = re.search(r'<h3><a href="([^"]+)"[^>]*>(.*?)</a></h3>', blk, re.S)
        d = re.search(r'class="date-time">\s*\w+ (\d{1,2}) (\w+) \S+ (\d{1,2}:\d{2} [ap]m)', blk)
        if not (t and d):
            continue
        tix = re.search(r'href="(https://www\.eventbrite\.com/e/[^"]+)"', blk)
        for yr in (lo.year, lo.year + 1):
            start = dt.datetime.strptime(f"{d.group(1)} {d.group(2)} {yr} {d.group(3)}", "%d %B %Y %I:%M %p")
            if start >= lo - dt.timedelta(days=60):
                break
        if lo <= start < hi:
            title = _clean(t.group(2))
            out.append({"venue": "Comic Strip Live", "title": title, "start": start, "link": t.group(1),
                        "notes": f"tickets: {tix.group(1) if tix else ''} | lineup-in-title"})
    return sorted(out, key=lambda x: x["start"])


# --- Brooklyn Comedy Collective: Squarespace events collection JSON.
def fetch_bcc(days=7):
    lo, hi = _window(days)
    url = "https://www.brooklyncc.com/show-schedule?format=json"
    out = []
    while url:
        d = json.loads(get(url))
        stop = False
        for e in d.get("upcoming", []):
            start = dt.datetime.fromtimestamp(e["startDate"] / 1000, NY).replace(tzinfo=None, microsecond=0)
            if start >= hi:
                stop = True
                break
            if start < lo:
                continue
            loc = e.get("location") or {}
            out.append({"venue": "Brooklyn Comedy Collective", "title": _clean(e.get("title")), "start": start,
                        "link": "https://www.brooklyncc.com" + e["fullUrl"],
                        "notes": f"{loc.get('addressTitle', '')} {loc.get('addressLine1', '')} | tags={','.join(e.get('tags', []))}"})
        p = d.get("pagination") or {}
        url = None if stop or not p.get("nextPage") else "https://www.brooklyncc.com" + p["nextPageUrl"] + "&format=json"
    return out


# --- Magnet Theater: WordPress theme, server-rendered day schedule /calendar/?date=YYYY-MM-DD
def fetch_magnet(days=7):
    lo, _ = _window(days)
    out = []
    for i in range(days + 1):
        day = lo + dt.timedelta(days=i)
        page = get(f"https://magnettheater.com/calendar/?date={day:%Y-%m-%d}")
        for b in page.split("<div class='post ")[1:]:
            t = re.search(r'show-title">\s*<a href="([^"]+)"[^>]*>([^<]+)', b)
            s = re.search(r"showtime'>\s*([^<]+)", b)
            if not (t and s):
                continue  # "No Shows" placeholder
            tm = dt.datetime.strptime(s.group(1).strip().upper(), "%I:%M%p").time()
            feat = re.findall(r'show-feat">(.*?)</span>', b, re.S)
            out.append({"venue": "Magnet Theater", "title": _clean(t.group(2)),
                        "start": dt.datetime.combine(day.date(), tm), "link": t.group(1),
                        "notes": "lineup: " + _clean(feat[0]) if feat else ""})
    return out


# --- The PIT: WordPress (custom xdgp calendar), server-rendered month grid /calendar/?month=October+2026
# Each <div id='day-<epoch of local midnight>'> holds <li class="event ..."> with title/link and performances.
def fetch_pit(days=7):
    lo, hi = _window(days)
    out = []
    for ym in _months(days):
        m = dt.datetime.strptime(ym, "%Y-%m")
        page = get("https://thepit-nyc.com/calendar/?month=" + m.strftime("%B+%Y"))
        for daym in re.finditer(r"<div id='day-(\d+)'(.*?)(?=<div id='day-|\Z)", page, re.S):
            date = dt.datetime.fromtimestamp(int(daym.group(1)), NY).date()
            for ev in re.split(r'<li class="event ', daym.group(2))[1:]:
                link = re.search(r'<a href="([^"]+)"', ev)
                title = re.search(r'event__title">(.*?)</p>', ev, re.S)
                if not (link and title):
                    continue
                for perf in re.findall(r'action__time">(.*?)</section>.*?venue__title">([^<]*)', ev, re.S):
                    buy = re.search(r'href="([^"]+)"', perf[0])
                    try:
                        tm = dt.datetime.strptime(_clean(perf[0]).upper(), "%I:%M%p").time()
                    except ValueError:
                        continue
                    start = dt.datetime.combine(date, tm)
                    if lo <= start < hi:
                        out.append({"venue": "The PIT", "title": _clean(title.group(1)), "start": start,
                                    "link": link.group(1),
                                    "notes": f"room: {_clean(perf[1])} | tickets: {buy.group(1) if buy else 'n/a (past/sold out/free)'}"})
    seen, res = set(), []
    for e in sorted(out, key=lambda x: x["start"]):
        k = (e["link"], e["start"])
        if k not in seen:
            seen.add(k)
            res.append(e)
    return res


# --- Asylum NYC: Tixr-hosted calendar (Next.js) with schema.org JSON-LD @graph of Events.
def fetch_asylum(days=7):
    lo, hi = _window(days)
    out = []
    for e in _jsonld_events(get("https://calendar.asylumnyc.com/")):
        start = _iso_to_ny(e["startDate"])
        if lo <= start < hi:
            out.append({"venue": "Asylum NYC", "title": _clean(e.get("name")), "start": start,
                        "link": e.get("url"), "notes": _clean(e.get("description"))[:200]})
    return sorted(out, key=lambda x: x["start"])


# --- Greenwich Village Comedy Club: WordPress + Tessera; homepage has show cards + eventObjects.push({...}).
def fetch_gvcc(days=7):
    lo, hi = _window(days)
    page = get("https://www.greenwichvillagecomedyclub.com/")
    out = []
    for c in page.split('tessera-show-card" id=')[1:]:
        ed = re.search(r'"eventDate": "([^"]+)"', c)
        t = re.search(r'card-title my-1">(.*?)</h3>', c, re.S)
        l = re.search(r'href="([^"]+/shows/[^"]+)"', c)
        if not (ed and t and l):
            continue
        start = dt.datetime.strptime(ed.group(1).upper(), "%m/%d/%Y %I:%M %p")
        if not (lo <= start < hi):
            continue
        names = []
        for key in ("mainArtist", "additionalArtists"):
            m = re.search(r'"%s": (\[.*?\])' % key, c, re.S)
            if m:
                try:
                    names += json.loads(m.group(1).replace("\\'", "'"))
                except ValueError:
                    pass
        room = re.search(r'tessera-venue[^>]*>.*?</i>\s*([^<]+)', c, re.S)
        out.append({"venue": "Greenwich Village Comedy Club", "title": _clean(t.group(1)), "start": start,
                    "link": l.group(1),
                    "notes": f"room: {room.group(1).strip() if room else ''} | lineup: {', '.join(names)}"})
    return sorted(out, key=lambda x: x["start"])


def _utc_to_ny(s):
    """'2026-10-19T23:30:00.000Z' or epoch ms -> naive NY datetime."""
    if isinstance(s, (int, float)):
        d = dt.datetime.fromtimestamp(s / 1000, dt.timezone.utc)
    else:
        d = dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
    return d.astimezone(NY).replace(tzinfo=None, microsecond=0)


def _next_flight(page):
    """Concatenate Next.js app-router RSC payload strings (self.__next_f.push)."""
    parts = re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', page)
    return ''.join(json.loads('"' + p + '"') for p in parts)


# ---------------------------------------------------------------- West Side Comedy Club
def fetch_westside(days=7):
    """punchup.live-built Next.js site; shows are in the RSC payload on the homepage."""
    s = _next_flight(get('https://www.westsidecomedyclub.com/'))
    dec = json.JSONDecoder()
    shows = {}
    for m in re.finditer(r'\{"id":"', s):
        try:
            o, _ = dec.raw_decode(s[m.start():])
        except ValueError:
            continue
        if isinstance(o, dict) and 'datetime' in o and 'ticket_link' in o:
            shows[o['id']] = o
    lo, hi = _window(days)
    out = []
    for o in shows.values():
        start = dt.datetime.fromisoformat(o['datetime'])  # naive NY wall clock
        if not (lo <= start < hi):
            continue
        lineup = [c.get('display_name') for c in (o.get('show_comedians') or []) if c.get('display_name')]
        notes = 'lineup: ' + ', '.join(lineup) if lineup else ''
        if o.get('is_sold_out'):
            notes = (notes + '; SOLD OUT').strip('; ')
        out.append(dict(venue='West Side Comedy Club', title=(o.get('title') or '').strip(),
                        start=start, link=o.get('ticket_link') or f"https://punchup.live/show/{o['id']}",
                        notes=notes))
    return sorted(out, key=lambda e: e['start'])


# ---------------------------------------------------------------- Stand Up NY (VenuePilot)
def fetch_standupny(days=7):
    lo, hi = _window(days)
    q = ('{ paginatedEvents(arguments:{accountIds:[2535], startDate:"%s", endDate:"%s", '
         'search:"", searchScope:"", page:1}) { collection { id name date startTime doorTime '
         'support promoter ticketsUrl status venue{name} artists{name} } metadata{totalPages} } }'
         % (lo.date().isoformat(), hi.date().isoformat()))
    d = json.loads(get('https://www.venuepilot.co/graphql', json_body={'query': q}))
    out = []
    for e in d['data']['paginatedEvents']['collection']:
        start = dt.datetime.fromisoformat(f"{e['date']}T{e.get('startTime') or e.get('doorTime') or '00:00:00'}")
        if not (lo <= start < hi):
            continue
        names = [a['name'] for a in e.get('artists') or []]
        notes = 'at ' + (e.get('venue') or {}).get('name', '')
        if names:
            notes += '; lineup: ' + ', '.join(names)
        out.append(dict(venue='Stand Up NY', title=e['name'], start=start,
                        link=e.get('ticketsUrl') or f"https://standupny.com/upcoming-shows/#/events/{e['id']}",
                        notes=notes))
    return sorted(out, key=lambda e: e['start'])


# ---------------------------------------------------------------- QED Astoria (Shopify + Evey Events)
def fetch_qed(days=7):
    lo, hi = _window(days)
    url = ('https://api.eveyevents.com/production-v2/storefront/calendar?shop=qed-astoria.myshopify.com'
           f'&startDate={lo.date()}&endDate={hi.date()}&currentDate={lo.date()}&lang=en')
    d = json.loads(get(url))
    out, seen = [], set()
    for s in d.get('schedule', []):
        start = _utc_to_ny(s['start'])
        key = s.get('id') or (s.get('title'), s['start'])
        if not (lo <= start < hi) or key in seen:
            continue
        seen.add(key)
        out.append(dict(venue='QED Astoria', title=html.unescape(s['title']), start=start,
                        link=s.get('url', '').replace('http://', 'https://'),
                        notes='mixed-programming venue (comedy, classes, book clubs, music)'))
    return sorted(out, key=lambda e: e['start'])


# ---------------------------------------------------------------- The Tiny Cupboard (JSON-LD)
def fetch_tinycupboard(days=7):
    lo, hi = _window(days)
    months = sorted({(lo + dt.timedelta(days=i)).strftime('%Y-%m') for i in range(days + 1)})
    out, seen = [], set()
    for ym in months:
        page = get(f'https://www.thetinycupboard.com/calendar/{ym}')
        for blob in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
            try:
                d = json.loads(blob)
            except ValueError:
                continue
            for e in d if isinstance(d, list) else [d]:
                if not isinstance(e, dict) or 'startDate' not in e:
                    continue
                start = _iso_to_ny(e['startDate'])
                link = (e.get('offers') or {}).get('url') or e.get('url')
                if not (lo <= start < hi) or link in seen:
                    continue
                seen.add(link)
                names = [p.get('name') for p in e.get('performer') or [] if isinstance(p, dict)]
                out.append(dict(venue='The Tiny Cupboard', title=html.unescape(e['name']).strip(),
                                start=start, link=link,
                                notes=('lineup: ' + ', '.join(names)) if names else ''))
    return sorted(out, key=lambda e: e['start'])


# ---------------------------------------------------------------- Young Ethel's (server-rendered HTML)
def _parse_clock(txt):
    m = re.match(r'\s*(\d{1,2})(?::(\d{2}))?\s*([ap])m', txt, re.I)
    if not m:
        return None
    h = int(m.group(1)) % 12 + (12 if m.group(3).lower() == 'p' else 0)
    return dt.time(h, int(m.group(2) or 0))


def fetch_youngethels(days=7, comedy_only=True):
    page = get('https://youngethels.com/events')
    lo, hi = _window(days)
    out = []
    # day headers: <time dateTime="2026-10-17T12:00:00.000Z" class="font-black" ...>
    days_ = re.split(r'(?=<time dateTime="[^"]+" class="font-black")', page)
    for chunk in days_[1:]:
        day = dt.date.fromisoformat(re.match(r'<time dateTime="(\d{4}-\d{2}-\d{2})', chunk).group(1))
        for tm, title in re.findall(
                r'<time dateTime="[^"]*" aria-label="([^"]*)" class="font-bold">.*?<span class="block">(.*?)</span>',
                chunk, re.S):
            title = html.unescape(re.sub(r'<!--.*?-->|<[^>]+>', '', title)).strip()
            mcat = re.search(r'\(([^()]*)\)\s*$', title)
            cat = mcat.group(1) if mcat else ''
            title = re.sub(r'\s*\([^()]*\)\s*$', '', title).strip()
            if comedy_only and 'comedy' not in cat.lower():
                continue
            t = _parse_clock(tm) or dt.time(0, 0)
            start = dt.datetime.combine(day, t)
            if lo <= start < hi:
                out.append(dict(venue="Young Ethel's", title=title, start=start,
                                link='https://youngethels.com/events', notes=f'category: {cat}; time text "{tm.strip()}"'))
    return sorted(out, key=lambda e: e['start'])


# ---------------------------------------------------------------- Club Cumming (Squarespace events collection)
def fetch_clubcumming(days=7):
    lo, hi = _window(days)
    out, url = [], 'https://clubcummingnyc.com/schedule?format=json'
    for _ in range(5):
        d = json.loads(get(url))
        items = d.get('upcoming') or []
        for e in items:
            start = _utc_to_ny(e['startDate'])
            if lo <= start < hi:
                out.append(dict(venue='Club Cumming', title=html.unescape(e['title']), start=start,
                                link='https://clubcummingnyc.com' + e['fullUrl'],
                                notes='queer cabaret/variety; mixed programming (DJ nights, karaoke, drag, comedy)'))
        pg = d.get('pagination') or {}
        if not items or not pg.get('nextPage') or _utc_to_ny(items[-1]['startDate']) >= hi:
            break
        url = 'https://clubcummingnyc.com' + pg['nextPageUrl'] + '&format=json'
    return sorted(out, key=lambda e: e['start'])


# ---------------------------------------------------------------- Pete's Candy Store (server-rendered HTML)
_MONTHS = {m: i for i, m in enumerate(
    ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
     'September', 'October', 'November', 'December'], 1)}


def fetch_petes(days=7, comedy_only=True):
    page = get('https://www.petescandystore.com/calendar')
    lo, hi = _window(days)
    out = []
    chunks = re.split(r'<div class="CalendarStyles-module__[A-Za-z0-9_]+__styledDate">', page)
    for chunk in chunks[1:]:
        m = re.match(r'(\w+) (\d+)\w* \(', chunk)
        if not m or m.group(1) not in _MONTHS:
            continue
        mon, dd = _MONTHS[m.group(1)], int(m.group(2))
        year = lo.year + (1 if mon < lo.month - 1 else 0)  # page has no year; roll over in Jan
        day = dt.date(year, mon, dd)
        for ev in re.split(r'<div class="CalendarStyles-module__[A-Za-z0-9_]+__event">', chunk)[1:]:
            tm = re.search(r'__styledTitle">(.*?)</h3>', ev, re.S)
            if not tm:
                continue
            title = html.unescape(re.sub(r'<[^>]+>', '', tm.group(1))).strip()
            href = re.search(r'__styledLink"[^>]*href="([^"]+)"', ev)
            ptxt = re.findall(r'__styledContent">([^<]*)</p>', ev)
            t = next((_parse_clock(p) for p in ptxt if _parse_clock(p)), dt.time(0, 0))
            desc = html.unescape(re.sub(r'<[^>]+>', ' ', ev))
            is_comedy = bool(re.search(r'comed|stand-?up|open mic|improv|sketch|storytell', desc, re.I))
            if comedy_only and not is_comedy:
                continue
            start = dt.datetime.combine(day, t)
            if lo <= start < hi:
                out.append(dict(venue="Pete's Candy Store", title=title, start=start,
                                link=href.group(1) if href else 'https://www.petescandystore.com/calendar',
                                notes='comedy guessed from description keywords' if is_comedy else 'music/other'))
    return sorted(out, key=lambda e: e['start'])


FETCHERS = [
    # part A
    fetch_comedy_cellar, fetch_caveat, fetch_union_hall, fetch_littlefield,
    fetch_bell_house, fetch_gotham, fetch_new_york_comedy_club,
    # part B
    fetch_comic_strip, fetch_grisly_pear, fetch_eastville, fetch_bcc, fetch_magnet,
    fetch_pit, fetch_asylum, fetch_rodneys, fetch_gvcc,
    # part C
    fetch_westside, fetch_standupny, fetch_qed, fetch_tinycupboard,
    fetch_youngethels, fetch_clubcumming, fetch_petes,
]
# fetch_ucb / fetch_the_stand are stubs (Cloudflare challenge) and return [].


def fetch_all(days=7):
    out, errors = [], {}
    for f in FETCHERS:
        try:
            out.extend(f(days))
        except Exception as ex:  # one venue failing must not sink the rest
            errors[f.__name__] = repr(ex)
    return sorted(out, key=lambda e: e['start']), errors


if __name__ == '__main__':
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    for f in FETCHERS:
        try:
            ev = f(days)
            print('== %s: %d' % (f.__name__, len(ev)))
            for e in ev[:4]:
                print('  ', e['start'], '|', e['venue'][:28], '|', e['title'][:55], '|', e['link'][:70], '|', e['notes'][:60])
        except Exception as ex:
            print('== %s FAILED: %r' % (f.__name__, ex))
