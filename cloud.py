#!/usr/bin/env python3
"""One unattended pull: listings plus travel times from a home address, written as JSON documents.

    python3 cloud.py --home "ADDRESS" [--out DIR] [YYYY-MM-DD ...]      default dates: today and tomorrow (New York)

Writes DIR/home.json and DIR/days/<date>.json. Whatever runs this (a scheduled Claude session) copies those
into the page's database as config/home and days/<date>. The address is an argument on purpose: it is never
stored in this repository.
"""
import argparse, datetime, json, os, sys

import fetch, routes, subway


def day_doc(date, home):
    doc = fetch.fetch(date)
    try:
        routes.fill(home, [(e['lat'], e['lon']) for e in doc['events']])
        route_error = None
    except Exception as ex:
        route_error = str(ex)[:160]
    cache, profile = routes.cached(home), subway.profile_for(date)
    for e in doc['events']:
        r = cache.get(routes.venue_key(e['lat'], e['lon']))
        if not r:
            continue
        sub, walk = r['subway'].get(profile), r['walk']
        if sub and walk and sub['min'] >= walk['min']:
            sub = None
        e['route'] = dict(walk=walk, bike=r['bike'], subway=sub)
    doc.update(profile=profile, home_label=home['label'], route_error=route_error)
    return doc


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
    os.makedirs(os.path.join(a.out, 'days'), exist_ok=True)
    json.dump(home, open(os.path.join(a.out, 'home.json'), 'w'))
    for d in dates:
        doc = day_doc(d, home)
        json.dump(doc, open(os.path.join(a.out, 'days', d.isoformat() + '.json'), 'w'))
        bad = [s['source'] for s in doc['sources'] if not s['ok']]
        print(d.isoformat(), len(doc['events']), 'events,', sum('route' in e for e in doc['events']), 'routed',
              '| failed sources:', sorted(set(bad)) or 'none', '| route error:', doc['route_error'])


if __name__ == '__main__':
    main()
