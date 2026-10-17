#!/usr/bin/env python3
"""Pull one day's events into data/events-YYYY-MM-DD.json. Stdlib only.

    python3 fetch.py               today (America/New_York)
    python3 fetch.py 2026-10-10    another day

Concerts come from pages that publish schema.org Event data in the HTML (Songkick's NYC listing plus a few
venue calendars). Theater, dance, opera, film and the fringe houses come from sources.py. Every source reports
how many events it gave, so a silent failure shows.
"""
import datetime, gzip, json, os, re, sys, urllib.request, zoneinfo

import routes, sources

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')
PINS = os.path.join(HERE, 'saved_venues.json')   # venues only (name, lat, lon), copied from my saved places
NY = zoneinfo.ZoneInfo('America/New_York')
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/129.0 Safari/537.36')
SK = 'https://www.songkick.com/metro-areas/7644-us-new-york-nyc'
MAX_KM = 30              # from the East Village: the five boroughs and the near shore, not Long Island or Jersey suburbs
VENUE_PAGES = [
    ('The Bell House', 'https://www.thebellhouseny.com/'),
    ('Brooklyn Paramount', 'https://www.brooklynparamount.com/shows'),
    ('Warsaw', 'https://www.warsawconcerts.com/'),
]


def today():
    return datetime.datetime.now(NY).date()


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Encoding': 'gzip',
                                               'Accept-Language': 'en-US,en;q=0.9'})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read()
        if r.headers.get('Content-Encoding') == 'gzip':
            body = gzip.decompress(body)
    return body.decode('utf-8', 'replace')


def ld_events(html):
    out = []

    def walk(x):
        if isinstance(x, list):
            for y in x:
                walk(y)
        elif isinstance(x, dict):
            if 'Event' in str(x.get('@type')):
                out.append(x)
            for k in ('@graph', 'itemListElement', 'item'):
                if k in x:
                    walk(x[k])
    for b in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            walk(json.loads(b))
        except ValueError:
            pass
    return out


def norm(s):
    s = re.sub(r'^the\s+', '', (s or '').lower())
    return re.sub(r'[^a-z0-9]+', '', s.replace('à', 'a').replace('è', 'e').replace('&', 'and'))


def pins():
    try:
        return json.load(open(PINS))
    except (OSError, ValueError):
        return []


def normalize(e, source, P):
    loc = e.get('location') or {}
    if isinstance(loc, list):
        loc = loc[0] if loc else {}
    start = str(e.get('startDate') or '')
    if len(start) < 10:
        return None
    addr = loc.get('address') or {}
    if isinstance(addr, str):
        street, city = addr, ''
    else:
        street, city = addr.get('streetAddress') or '', addr.get('addressLocality') or ''
    city = re.sub(r'\s*\(NYC\)', '', city)
    full_street, street = street, street.split(',')[0].strip()
    geo = loc.get('geo') or {}
    venue = (loc.get('name') or '').strip()
    lat, lon = geo.get('latitude'), geo.get('longitude')
    nv = norm(venue)
    by_name = next((p for p in P if norm(p['name']) == nv), None) if nv else None
    if lat is None and by_name:
        lat, lon = by_name['lat'], by_name['lon']
    if lat is None and street:
        g = routes.geocode(f'{full_street}, {city or "New York"}')
        if g:
            lat, lon = g['lat'], g['lon']
    if lat is None:
        return None
    lat, lon = float(lat), float(lon)
    if routes.km(lat, lon, 40.7306, -73.9866) > MAX_KM:
        return None
    pinned = bool(by_name) or any(routes.km(lat, lon, p['lat'], p['lon']) < 0.07 for p in P)
    title = re.sub(r'\s+', ' ', e.get('name') or '').strip()
    if venue and title.lower().endswith(' @ ' + venue.lower()):
        title = title[:-len(venue) - 3]
    acts = [p.get('name') for p in (e.get('performer') or []) if isinstance(p, dict) and p.get('name')] \
        if isinstance(e.get('performer'), list) else []
    return dict(title=title, date=start[:10], time=start[11:16] if 'T' in start else None,
                venue=venue, street=street, city=city, lat=lat, lon=lon, pinned=pinned,
                acts=[a for a in acts if a.lower() not in title.lower()][:4],
                url=(e.get('url') or '').split('?utm_')[0], source=source,
                kind='comedy' if 'Comedy' in str(e.get('@type')) else 'music',
                cancelled='Cancel' in str(e.get('eventStatus')))


def is_pinned(e, P):
    nv = norm(e['venue'])
    return any(norm(p['name']) == nv or routes.km(e['lat'], e['lon'], p['lat'], p['lon']) < 0.07 for p in P)


def fetch(date, extra=None, extra_report=None):
    """extra / extra_report: that day's events and report lines from sources.collect(), when the caller has
    already fetched a range of days in one go. Left out, this fetches them for the one day."""
    P = pins()
    report, events = [], []

    def take(name, url):
        try:
            got = [normalize(e, name, P) for e in ld_events(get(url))]
        except Exception as ex:
            report.append(dict(source=name, url=url, ok=False, error=str(ex)[:120]))
            return None
        got = [g for g in got if g]
        mine = [g for g in got if g['date'] == date.isoformat() and not g['cancelled']]
        report.append(dict(source=name, url=url, ok=True, found=len(got), on_date=len(mine)))
        events.extend(mine)
        return got

    if date == today():
        for page in range(1, 9):
            got = take('Songkick', f'{SK}/tonight?page={page}')
            if not got:
                break
    else:
        for page in range(1, 16):
            got = take('Songkick', f'{SK}?page={page}')
            if not got or min(g['date'] for g in got) > date.isoformat():
                break
    for name, url in VENUE_PAGES:
        take(name, url)

    if extra is None:
        ev, rp = sources.collect([date])
        extra, extra_report = ev[date.isoformat()], rp[date.isoformat()]
    report.extend(extra_report or [])
    for e in extra:
        if routes.km(e['lat'], e['lon'], 40.7306, -73.9866) <= MAX_KM:
            events.append(dict(e, pinned=is_pinned(e, P), cancelled=False))

    # The same performance can arrive from a house's own ticketing and from an aggregator. Keep the house's.
    rank = lambda e: 2 if e['source'] == 'TodayTix' else 1 if e['source'] == 'Songkick' else 0
    seen, out = {}, []
    for e in sorted(events, key=lambda e: (e['time'] or '99:99', rank(e), e['venue'])):
        # same start time and within about 200 m (a fixed grid would split a building that straddles a cell edge)
        near = [o for o in seen.get(e['time'], []) if routes.km(o['lat'], o['lon'], e['lat'], e['lon']) <= 0.2]
        same = [o for o in near if o['source'] != e['source'] and
                (norm(o['venue']) == norm(e['venue']) or norm(o['title'])[:8] == norm(e['title'])[:8])]
        exact = [o for o in near if o['source'] == e['source'] and norm(o['venue']) == norm(e['venue'])
                 and norm(o['title'])[:12] == norm(e['title'])[:12]]
        if same or exact:
            continue
        seen.setdefault(e['time'], []).append(e)
        e['id'] = f"{e['date']}|{norm(e['venue'])}|{e['time'] or ''}|{norm(e['title'])[:24]}"
        del e['cancelled']
        out.append(e)
    doc = dict(date=date.isoformat(), fetched_at=datetime.datetime.now(NY).isoformat(timespec='seconds'),
               sources=report, events=out)
    os.makedirs(DATA, exist_ok=True)
    path = os.path.join(DATA, f'events-{date.isoformat()}.json')
    json.dump(doc, open(path + '.tmp', 'w'), indent=1)
    os.replace(path + '.tmp', path)
    return doc


if __name__ == '__main__':
    d = datetime.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else today()
    doc = fetch(d)
    for r in doc['sources']:
        print(r)
    import collections
    print(len(doc['events']), 'events on', doc['date'], '|', sum(e['pinned'] for e in doc['events']), 'at saved venues',
          '|', sum(e['time'] is None for e in doc['events']), 'with no time', '|',
          dict(collections.Counter(e['kind'] for e in doc['events'])))
