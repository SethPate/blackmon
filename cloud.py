#!/usr/bin/env python3
"""One unattended pull: listings plus travel times from a home address, written as JSON documents.

    python3 cloud.py --home "ADDRESS" [--out DIR] [YYYY-MM-DD ...]      default dates: today and tomorrow (New York)

Writes DIR/home.json, DIR/almanac.json (the next big days), DIR/days/<date>.json (the listings) and
DIR/routes/<date>.json (travel times by venue). Whatever runs this (a scheduled Claude session) copies those into
the page's database as config/home, config/almanac, days/<date> and routes/<date>. The address is an argument on purpose: it is never
stored in this repository.
"""
import argparse, datetime, json, os, sys

import fetch, routes, sources, subway


KEEP = ('title', 'time', 'until', 'venue', 'street', 'city', 'pinned', 'acts', 'url', 'source', 'kind', 'note')
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


def coming_up(today, n=10):
    """The next big days, for the page's side rail."""
    rows = sorted((a for a in _load('almanac.json') if a['end'] >= today.isoformat()), key=lambda a: a['start'])
    return dict(as_of=today.isoformat(), items=[{k: a.get(k) for k in ('title', 'start', 'end', 'venue', 'url', 'note')}
                                                for a in rows[:n]])


def day_docs(date, home, extra, extra_report):
    """(events document, routes document) for one day. Travel times live in their own document, keyed by venue,
    so a long night of listings stays well under the store's 256 KiB-per-document limit."""
    doc = fetch.fetch(date, extra, extra_report)
    P = fetch.pins()
    kept = hand_kept(date)
    for e in kept:
        e['pinned'] = e.get('lat') is not None and fetch.is_pinned(e, P)
    doc['events'] = sorted(doc['events'] + kept, key=lambda e: (e['time'] or '99:99', e['kind'] == 'standing'))
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
        day, rts = day_docs(d, home, extra[iso], report[iso])
        json.dump(day, open(os.path.join(a.out, 'days', iso + '.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
        json.dump(rts, open(os.path.join(a.out, 'routes', iso + '.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
        bad = sorted({s['source'] for s in day['sources'] if not s['ok']})
        size = max(os.path.getsize(os.path.join(a.out, s, iso + '.json')) for s in ('days', 'routes')) // 1024
        print(iso, len(day['events']), 'events,', sum(e['v'] in rts['venues'] for e in day['events']), 'routed,',
              sum(e['v'] is None for e in day['events']), 'with no single place',
              '| failed sources:', bad or 'none', '| route error:', day['route_error'], f'| largest document {size} KiB')


if __name__ == '__main__':
    main()
