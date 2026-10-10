#!/usr/bin/env python3
"""One unattended pull: listings plus travel times from a home address, written as JSON documents.

    python3 cloud.py --home "ADDRESS" [--out DIR] [YYYY-MM-DD ...]      default dates: today and tomorrow (New York)

Writes DIR/home.json, DIR/almanac.json (the next big days), DIR/days/<date>.json (the listings) and
DIR/routes/<date>.json (travel times by venue). Whatever runs this (a scheduled Claude session) copies those into
the page's database as config/home, config/almanac, days/<date> and routes/<date>. The address is an argument on purpose: it is never
stored in this repository.
"""
import argparse, datetime, json, os, re, sys, time, urllib.parse, urllib.request

import fetch, routes, sources, subway


KEEP = ('title', 'time', 'until', 'venue', 'street', 'city', 'pinned', 'acts', 'url', 'source', 'kind', 'note', 'via')
KINDS = ('theater', 'dance', 'opera', 'music', 'film', 'comedy', 'talk', 'games', 'art', 'other')
BOROUGHS = ('Manhattan', 'Brooklyn', 'Queens', 'Bronx', 'Staten Island')
HERE = os.path.dirname(os.path.abspath(__file__))
WEEK = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']


def _load(name):
    try:
        return json.load(open(os.path.join(HERE, name)))
    except (OSError, ValueError):
        return []


def hand_kept(date):
    """Rows that come from the two hand-kept files rather than a feed: almanac.json (big dated city events) and
    standing.json (things that are simply there on certain weekdays: a museum's late night, rush tickets, a bar)."""
    iso, out = date.isoformat(), []
    base = dict(pinned=False, acts=[], until=None)
    for a in _load('almanac.json'):
        if a['start'] <= iso <= a['end']:
            out.append(dict(base, title=a['title'], time=a.get('time'), venue=a.get('venue') or '', street=a.get('street') or '',
                            city=a.get('city') or '', url=a.get('url'), source='Almanac', kind='big day',
                            note=a.get('note'), lat=a.get('lat'), lon=a.get('lon')))
    for s in _load('standing.json'):
        if s.get('valid_from', '') > iso:
            continue
        for w in s.get('when') or []:
            if WEEK[date.weekday()] in w.get('days', []) and (not w.get('nth') or (date.day - 1) // 7 + 1 in w['nth']):
                out.append(dict(base, title=s['title'], time=w.get('start'), until=w.get('end'), venue=s.get('venue') or '',
                                street=s.get('street') or '', city=s.get('city') or '', url=s.get('url'), source='Standing',
                                kind='standing', note=s.get('note'), lat=s.get('lat'), lon=s.get('lon')))
    return out


_place_last = [0.0]


def _tokens(s):
    s = (s or '').lower().replace("'", '').replace('\u2019', '')
    return set(re.findall(r'[a-z0-9]+', s)) - {'the', 'at', 'of', 'and', 'a', 'new', 'york', 'nyc'}


def find_venue(name, borough):
    """(street, lat, lon) for a named place, or None. Asks OpenStreetMap's search, then the city's own, and
    accepts an answer only when every word of the name is in the name that came back and it is in the right
    borough: a missing pin is better than a wrong one."""
    want = _tokens(name)
    if not want or borough not in BOROUGHS:
        return None
    county = {'Manhattan': 'New York County', 'Brooklyn': 'Kings County', 'Queens': 'Queens County',
              'Bronx': 'Bronx County', 'Staten Island': 'Richmond County'}[borough]
    try:
        time.sleep(max(0, _place_last[0] + 1.1 - time.time()))          # one request a second, as its policy asks
        q = urllib.parse.urlencode(dict(q=f'{name}, {borough}, New York', format='jsonv2', limit=3, addressdetails=1,
                                        viewbox='-74.27,40.49,-73.68,40.92', bounded=1))
        req = urllib.request.Request('https://nominatim.openstreetmap.org/search?' + q, headers={'User-Agent': routes.UA})
        hits = json.load(urllib.request.urlopen(req, timeout=20))
        _place_last[0] = time.time()
        for r in hits:
            if want <= _tokens(r.get('name') or r.get('display_name', '').split(',')[0]) and county in r.get('display_name', ''):
                a = r.get('address') or {}
                street = ' '.join(x for x in (a.get('house_number'), a.get('road')) if x)
                return street, float(r['lat']), float(r['lon'])
    except Exception:
        _place_last[0] = time.time()
    try:
        q = urllib.parse.urlencode(dict(text=f'{name}, {borough}', size=3, layers='venue'))
        d = json.load(urllib.request.urlopen(urllib.request.Request(
            'https://geosearch.planninglabs.nyc/v2/search?' + q, headers={'User-Agent': routes.UA}), timeout=20))
        for f in d.get('features') or []:
            p = f['properties']
            if p.get('borough') == borough and want <= _tokens(p.get('name')):
                lon, lat = f['geometry']['coordinates']
                return '', lat, lon
    except Exception:
        pass
    return None


def skint_rows(path, date, known):
    """Entries a model read out of the Skint's posts (see skint.py), checked and placed for one day.

    The Skint usually names a venue and a neighbourhood but no address. An entry is given coordinates when its
    venue is one this pull already knows (another source's event that day, a saved venue, a house in
    sources.py), when it has a street address that looks up, or when find_venue() is sure of the name.
    Otherwise it is listed without travel times rather than pinned on a guess. Each row keeps a link back to the Skint post it came from."""
    try:
        items = json.load(open(path)) if path else []
    except (OSError, ValueError):
        return []
    out, iso = [], date.isoformat()
    ok_time = lambda t: isinstance(t, str) and len(t) == 5 and t[2] == ':' and t[:2].isdigit() and t[3:].isdigit()
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict) or it.get('date') != iso or it.get('sponsored') or not str(it.get('title') or '').strip():
            continue
        venue, borough = str(it.get('venue') or '').strip(), str(it.get('borough') or '').strip()
        lat = lon = None
        hit = known.get(fetch.norm(venue)) if venue else None
        if hit:
            lat, lon = hit
        elif it.get('address') and borough in BOROUGHS:
            try:
                g = routes.geocode(f"{it['address']}, {borough}")
            except Exception:
                g = None
            if g:
                lat, lon = g['lat'], g['lon']
        street = str(it.get('address') or '').strip()
        if lat is None and venue:
            found = find_venue(venue, borough)
            if found:
                street, lat, lon = found[0] or street, found[1], found[2]
        url = it.get('url') if str(it.get('url') or '').startswith('http') else None
        post = it.get('post') if str(it.get('post') or '').startswith('https://theskint.com/') else 'https://theskint.com/'
        out.append(dict(title=str(it['title']).strip()[:140], time=it.get('time') if ok_time(it.get('time')) else None,
                        until=it.get('until') if ok_time(it.get('until')) else None, venue=venue[:80],
                        street=(street or str(it.get('area') or '').strip())[:80], city=borough if borough in BOROUGHS else '',
                        pinned=False, acts=[], url=url, source='the skint', kind=it.get('kind') if it.get('kind') in KINDS else 'other',
                        note=str(it.get('price') or '').strip()[:80] or None, via=dict(name='the skint', url=post), lat=lat, lon=lon))
    return out


def coming_up(today, n=10):
    """The next big days, for the page's side rail."""
    rows = sorted((a for a in _load('almanac.json') if a['end'] >= today.isoformat()), key=lambda a: a['start'])
    return dict(as_of=today.isoformat(), items=[{k: a.get(k) for k in ('title', 'start', 'end', 'venue', 'url', 'note')}
                                                for a in rows[:n]])


def day_docs(date, home, extra, extra_report, skint=None):
    """(events document, routes document) for one day. Travel times live in their own document, keyed by venue,
    so a long night of listings stays well under the store's 256 KiB-per-document limit."""
    doc = fetch.fetch(date, extra, extra_report)
    P = fetch.pins()
    kept = hand_kept(date)
    for e in kept:
        e['pinned'] = e.get('lat') is not None and fetch.is_pinned(e, P)
    known = {fetch.norm(p['name']): (p['lat'], p['lon']) for p in P}
    known.update({fetch.norm(p[0]): (p[3], p[4]) for p in sources.PLACES.values() if p})
    known.update({fetch.norm(s['venue']): (s['lat'], s['lon']) for s in _load('standing.json') if s.get('lat') is not None})
    known.update({fetch.norm(e['venue']): (e['lat'], e['lon']) for e in doc['events'] if e.get('venue')})
    seen = {(e['time'], fetch.norm(e['venue'])) for e in doc['events']}
    sk = [e for e in skint_rows(skint, date, known) if (e['time'], fetch.norm(e['venue'])) not in seen]
    for e in sk:
        e['pinned'] = e['lat'] is not None and fetch.is_pinned(e, P)
    if skint:
        doc['sources'].append(dict(source='the skint', ok=True, on_date=len(sk)))
    doc['events'] = sorted(doc['events'] + sk + kept, key=lambda e: (e['time'] or '99:99', e['kind'] == 'standing'))
    try:
        routes.fill(home, [(e['lat'], e['lon']) for e in doc['events'] if e.get('lat') is not None])
        route_error = None
    except Exception as ex:
        route_error = str(ex)[:160]
    cache, profile = routes.cached(home), subway.profile_for(date)
    venues, events = {}, []
    for e in doc['events']:
        v = routes.venue_key(e['lat'], e['lon']) if e.get('lat') is not None else None
        r = cache.get(v) if v else None
        if r and v not in venues:
            sub, walk = r['subway'].get(profile), r['walk']
            if sub and walk and sub['min'] >= walk['min']:
                sub = None
            venues[v] = dict(walk=walk, bike=r['bike'], subway=sub)
        events.append(dict({k: e.get(k) for k in KEEP if e.get(k) not in (None, [], '')}, v=v))
    day = dict(date=doc['date'], fetched_at=doc['fetched_at'], sources=doc['sources'], events=events,
               profile=profile, home_label=home['label'], route_error=route_error)
    return day, dict(date=doc['date'], profile=profile, venues=venues)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--home', required=True)
    ap.add_argument('--out', default='out')
    ap.add_argument('--skint', help='JSON file of entries read from the Skint (see skint.py)')
    ap.add_argument('dates', nargs='*')
    a = ap.parse_args()
    g = routes.geocode(a.home)
    if not g:
        sys.exit(f'could not find the home address in NYC: {a.home!r}')
    home = dict(address=a.home, label=g['label'], lat=g['lat'], lon=g['lon'])
    t = fetch.today()
    dates = [datetime.date.fromisoformat(d) for d in a.dates] or [t, t + datetime.timedelta(days=1)]
    for sub in ('days', 'routes'):
        os.makedirs(os.path.join(a.out, sub), exist_ok=True)
    json.dump(home, open(os.path.join(a.out, 'home.json'), 'w'))
    json.dump(coming_up(t), open(os.path.join(a.out, 'almanac.json'), 'w'), ensure_ascii=False)
    extra, report = sources.collect(dates)
    for d in dates:
        iso = d.isoformat()
        day, rts = day_docs(d, home, extra[iso], report[iso], a.skint)
        json.dump(day, open(os.path.join(a.out, 'days', iso + '.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
        json.dump(rts, open(os.path.join(a.out, 'routes', iso + '.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
        bad = sorted({s['source'] for s in day['sources'] if not s['ok']})
        size = max(os.path.getsize(os.path.join(a.out, s, iso + '.json')) for s in ('days', 'routes')) // 1024
        print(iso, len(day['events']), 'events,', sum(e['v'] in rts['venues'] for e in day['events']), 'routed,',
              sum(e['v'] is None for e in day['events']), 'with no single place',
              '| failed sources:', bad or 'none', '| route error:', day['route_error'], f'| largest document {size} KiB')


if __name__ == '__main__':
    main()
