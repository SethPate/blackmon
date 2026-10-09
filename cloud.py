#!/usr/bin/env python3
"""One unattended pull: listings plus travel times from a home address, written as JSON documents.

    python3 cloud.py --home "ADDRESS" [--out DIR] [YYYY-MM-DD ...]      default dates: today and tomorrow (New York)

Writes DIR/home.json, DIR/days/<date>.json (the listings) and DIR/routes/<date>.json (travel times by venue).
Whatever runs this (a scheduled Claude session) copies those into the page's database as config/home,
days/<date> and routes/<date>. The address is an argument on purpose: it is never
stored in this repository.
"""
import argparse, datetime, json, os, sys

import fetch, routes, sources, subway


KEEP = ('title', 'time', 'venue', 'street', 'city', 'pinned', 'acts', 'url', 'source', 'kind')


def day_docs(date, home, extra, extra_report):
    """(events document, routes document) for one day. Travel times live in their own document, keyed by venue,
    so a long night of listings stays well under the store's 256 KiB-per-document limit."""
    doc = fetch.fetch(date, extra, extra_report)
    try:
        routes.fill(home, [(e['lat'], e['lon']) for e in doc['events']])
        route_error = None
    except Exception as ex:
        route_error = str(ex)[:160]
    cache, profile = routes.cached(home), subway.profile_for(date)
    venues, events = {}, []
    for e in doc['events']:
        v = routes.venue_key(e['lat'], e['lon'])
        r = cache.get(v)
        if r and v not in venues:
            sub, walk = r['subway'].get(profile), r['walk']
            if sub and walk and sub['min'] >= walk['min']:
                sub = None
            venues[v] = dict(walk=walk, bike=r['bike'], subway=sub)
        events.append(dict({k: e.get(k) for k in KEEP}, v=v))
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
    extra, report = sources.collect(dates)
    for d in dates:
        iso = d.isoformat()
        day, rts = day_docs(d, home, extra[iso], report[iso])
        json.dump(day, open(os.path.join(a.out, 'days', iso + '.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
        json.dump(rts, open(os.path.join(a.out, 'routes', iso + '.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
        bad = sorted({s['source'] for s in day['sources'] if not s['ok']})
        size = max(os.path.getsize(os.path.join(a.out, s, iso + '.json')) for s in ('days', 'routes')) // 1024
        print(iso, len(day['events']), 'events,', sum(e['v'] in rts['venues'] for e in day['events']), 'routed',
              '| failed sources:', bad or 'none', '| route error:', day['route_error'], f'| largest document {size} KiB')


if __name__ == '__main__':
    main()
