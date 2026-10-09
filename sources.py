#!/usr/bin/env python3
"""Non-concert sources: theater, dance, opera, film and the fringe houses. Stdlib only.

    python3 sources.py 2026-10-10            print what each source gives for a day
    python3 sources.py --build-venues        refresh tt_venues.json (addresses of TodayTix venues)

Most of these read a ticketing system rather than a venue's web page, because one reader then covers every
house that sells through it:

  OvationTix   La MaMa, Performance Space New York, Abrons, The Bushwick Starr, The Brick, Danspace Project,
               Roulette, Dixon Place
  Spektrix     St. Ann's Warehouse, New York Theatre Workshop, PAC NYC, Soho Rep
  TodayTix     Broadway and Off-Broadway plays and musicals, the Met, City Center and others (about 300 shows)
  BAM          its own calendar feed, which includes the cinemas

collect(dates) fetches each source once for the whole date range and returns events grouped by day, plus a
report line per source and day so a source that silently returns nothing is visible on the page.
"""
import datetime, gzip, html, json, os, re, sys, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
TT_VENUES = os.path.join(HERE, 'tt_venues.json')
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/129.0 Safari/537.36')

# name, street, city, lat, lon. One address per organisation: a house with two rooms a block apart is one pin.
PLACES = {
    'lamama':   ('La MaMa', '66 E. 4th St.', 'Manhattan', 40.72641, -73.99052),
    'psny':     ('Performance Space New York', '150 First Ave.', 'Manhattan', 40.72857, -73.98424),
    'abrons':   ('Abrons Arts Center', '466 Grand St.', 'Manhattan', 40.71512, -73.98383),
    'starr':    ('The Bushwick Starr', '419 Eldert St.', 'Brooklyn', 40.69550, -73.90481),
    'brick':    ('The Brick', '579 Metropolitan Ave.', 'Brooklyn', 40.71430, -73.94974),
    'danspace': ('Danspace Project', '131 E. 10th St.', 'Manhattan', 40.73042, -73.98718),
    'roulette': ('Roulette', '509 Atlantic Ave.', 'Brooklyn', 40.68568, -73.98074),
    'dixon':    ('Dixon Place', '161A Chrystie St.', 'Manhattan', 40.72093, -73.99296),
    'stanns':   ("St. Ann's Warehouse", '45 Water St.', 'Brooklyn', 40.70367, -73.99296),
    'nytw':     ('New York Theatre Workshop', '79 E. 4th St.', 'Manhattan', 40.72660, -73.99012),
    'pac':      ('PAC NYC', '251 Fulton St.', 'Manhattan', 40.71259, -74.01206),
    'sohorep':  ('Soho Rep', '416 W. 42nd St.', 'Manhattan', 40.75862, -73.99335),
    'bam':      ('BAM', '30 Lafayette Ave.', 'Brooklyn', 40.68650, -73.97780),
}
OVATION = [('lamama', 42, 'theater'), ('psny', 203, 'theater'), ('abrons', 209, 'theater'), ('starr', 34289, 'theater'),
           ('brick', 122, 'theater'), ('danspace', 2742, 'dance'), ('roulette', 36368, 'music'), ('dixon', 35526, 'theater')]
SPEKTRIX = [('stanns', 'https://system.spektrix.com/stannswarehouse', 'https://stannswarehouse.org/'),
            ('nytw', 'https://tickets.nytw.org/newyorktheatreworkshop', 'https://www.nytw.org/'),
            ('pac', 'https://tickets.pacnyc.org/pacnyc', 'https://pacnyc.org/whats-on/'),
            ('sohorep', 'https://system.spektrix.com/sohorep', 'https://sohorep.org/')]
TT_KINDS = {'Plays': 'theater', 'Musicals': 'theater', 'Opera': 'opera', 'Dance': 'dance', 'Concerts': 'music',
            'Comedy Shows': 'comedy', 'Cabaret': 'music', 'Films': 'film', 'Immersive Experiences': 'theater',
            'Circus and Magic': 'theater', 'Conversations': 'talk', 'Events': 'other'}
GENRE_WORDS = [('film', 'film'), ('cinema', 'film'), ('opera', 'opera'), ('dance', 'dance'), ('ballet', 'dance'),
               ('theat', 'theater'), ('music', 'music'), ('comedy', 'comedy'), ('talk', 'talk'), ('literary', 'talk')]


def get(url, headers=None, timeout=30):
    h = {'User-Agent': UA, 'Accept-Encoding': 'gzip', 'Accept': 'application/json, text/html;q=0.9, */*;q=0.8'}
    h.update(headers or {})
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
        body = r.read()
        if r.headers.get('Content-Encoding') == 'gzip':
            body = gzip.decompress(body)
    return body.decode('utf-8', 'replace')


def clean(s):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', s or ''))).strip()


def kind_of(text, default):
    t = (text or '').lower()
    return next((k for w, k in GENRE_WORDS if w in t), default)


def event(place, title, date, time, url, source, kind, acts=()):
    name, street, city, lat, lon = place
    return dict(title=clean(title), date=date, time=time or None, venue=name, street=street, city=city, lat=lat,
                lon=lon, acts=[clean(a) for a in acts if a and clean(a)][:3], url=url, source=source, kind=kind)


def ovationtix(d0, d1):
    out = {}
    for key, client, kind in OVATION:
        place = PLACES[key]
        try:
            days = json.loads(get(f'https://web.ovationtix.com/trs/api/rest/CalendarProductions?startDate={d0}&endDate={d1}',
                                  {'clientId': str(client), 'newCIRequest': 'true'}))
            evs = []
            for day in days:
                for p in day.get('productions') or []:
                    name = re.sub(r'^\d{4}/\d\d/\d\d\s+', '', p.get('name') or '')
                    if p.get('hidden') or 'livestream' in name.lower() or '[LIVESTR' in name:
                        continue
                    for s in p.get('showtimes') or []:
                        t = s.get('performanceStartTime') or ''
                        if s.get('isCancelled') or s.get('isVisible') is False or len(t) < 16:
                            continue
                        evs.append(event(place, name, t[:10], t[11:16],
                                         f"https://ci.ovationtix.com/{client}/production/{p.get('productionId')}",
                                         place[0], kind, [p.get('subtitle')]))
            out[place[0]] = evs
        except Exception as ex:
            out[place[0]] = ex
    return out


def spektrix(d0, d1):
    out = {}
    end = (datetime.date.fromisoformat(d1) + datetime.timedelta(days=1)).isoformat()
    for key, base, site in SPEKTRIX:
        place = PLACES[key]
        try:
            inst = json.loads(get(f'{base}/api/v3/instances?startFrom={d0}&startTo={end}'))
            names = {e['id']: e for e in json.loads(get(f'{base}/api/v3/events'))} if inst else {}
            evs = []
            for i in inst:
                e = names.get((i.get('event') or {}).get('id'))
                if not e or i.get('cancelled') or i.get('attribute_VirtualEvent'):
                    continue
                t = i.get('start') or ''
                evs.append(event(place, e.get('name'), t[:10], t[11:16], e.get('webUrl') or site, place[0],
                                 kind_of(e.get('attribute_Genre1'), 'theater')))
            out[place[0]] = evs
        except Exception as ex:
            out[place[0]] = ex
    return out


def tribe(d0, d1):
    out = {}
    for key, host in (('brick', 'www.bricktheater.com'),):
        place = PLACES[key]
        try:
            q = urllib.parse.urlencode(dict(start_date=d0, end_date=d1 + ' 23:59:59', per_page=50))
            d = json.loads(get(f'https://{host}/wp-json/tribe/events/v1/events?{q}'))
            out[place[0] + ' (site)'] = [event(place, e.get('title'), e['start_date'][:10], e['start_date'][11:16],
                                               e.get('url'), place[0], 'theater') for e in d.get('events') or []]
        except Exception as ex:
            out[place[0] + ' (site)'] = ex
    return out


def bam(d0, d1):
    us = lambda d: f'{d[5:7]}/{d[8:10]}/{d[:4]}'
    try:
        items = json.loads(get(f'https://www.bam.org/api/BAMApi/GetCalendarEventsByDayWithOnGoing?start={us(d0)}&end={us(d1)}'))
        evs, seen = [], set()
        for it in items:
            kind = kind_of(it.get('genres'), 'other')
            url = 'https://www.bam.org' + it['moreLink'] if (it.get('moreLink') or '').startswith('/') else it.get('buyLink')
            for p in it.get('performances') or []:
                if (it.get('id'), p) in seen or not isinstance(p, str):
                    continue
                seen.add((it.get('id'), p))
                place = PLACES['bam'] if kind != 'film' else ('BAM Rose Cinemas',) + PLACES['bam'][1:]
                evs.append(event(place, it.get('name'), p[:10], p[11:16], url, 'BAM', kind))
        return {'BAM': evs}
    except Exception as ex:
        return {'BAM': ex}


def tt_venues():
    try:
        return json.load(open(TT_VENUES))
    except (OSError, ValueError):
        return {}


def tt_venue_lookup(slug):
    """Address and coordinates from a TodayTix venue page. None if the page does not give both."""
    h = get(f'https://www.todaytix.com/nyc/venues/{slug}')
    m = re.search(r'"name":"([^"]+)","url":"https://www\.todaytix\.com/nyc/venues/' + re.escape(slug) +
                  r'","address":\{[^}]*?"streetAddress":"([^"]+)"[^}]*?"addressLocality":"([^"]*)"', h)
    geo = [(float(a), float(b)) for a, b in re.findall(r'"latitude":(-?[0-9.]+),"longitude":(-?[0-9.]+)', h)]
    geo = [g for g in geo if 40.4 < g[0] < 41.0 and -74.3 < g[1] < -73.6]
    if not m or not geo:
        return None
    street = re.sub(r'\s*\(.*?\)', '', m.group(2)).strip()
    return dict(name=html.unescape(m.group(1)), street=street, city=m.group(3), lat=geo[0][0], lon=geo[0][1])


def todaytix(d0, d1):
    try:
        shows = json.loads(get('https://api.todaytix.com/api/v2/shows?location=1&limit=500'))['data']
        V = tt_venues()
        want = []
        for s in shows:
            kind = TT_KINDS.get((s.get('category') or {}).get('name'))
            start, end = s.get('startDate'), s.get('endDate')
            if not kind or s.get('productType') != 'SHOW' or not s.get('venueUrl'):
                continue
            if (start and start > d1) or (end and end != 'null' and end < d0):
                continue
            want.append((s, kind))

        def one(sk):
            s, kind = sk
            slug = s['venueUrl']
            v = V.get(slug)
            if v is None:
                try:
                    v = V[slug] = tt_venue_lookup(slug) or False
                except Exception:
                    v = False
            if not v:
                return []
            times = json.loads(get(f"https://api.todaytix.com/api/v2/shows/{s['id']}/showtimes?startDate={d0}&endDate={d1}"))['data']
            place = (s.get('venue') or v['name'], v['street'], v['city'], v['lat'], v['lon'])
            return [event(place, s.get('displayName'), t['localDate'], t['localTime'],
                          f"https://www.todaytix.com/nyc/shows/{s['id']}-{s.get('slug', '')}", 'TodayTix', kind)
                    for t in times if d0 <= t.get('localDate', '') <= d1]
        evs, failed = [], 0
        with ThreadPoolExecutor(6) as ex:
            for r in ex.map(lambda sk: _safe(one, sk), want):
                if r is None:
                    failed += 1
                else:
                    evs += r
        if failed > len(want) / 2:
            raise RuntimeError(f'{failed} of {len(want)} showtime lookups failed')
        return {'TodayTix': evs}
    except Exception as ex:
        return {'TodayTix': ex}


def _safe(f, x):
    try:
        return f(x)
    except Exception:
        return None


def collect(dates):
    """dates: list of datetime.date. Returns ({iso date: [events]}, {iso date: [report entries]})."""
    days = sorted(d.isoformat() for d in dates)
    d0, d1 = days[0], days[-1]
    results = {}
    with ThreadPoolExecutor(5) as ex:
        for r in ex.map(lambda f: f(d0, d1), (ovationtix, spektrix, bam, todaytix)):
            results.update(r)
    events, report = {d: [] for d in days}, {d: [] for d in days}
    for name, got in results.items():
        for d in days:
            if isinstance(got, Exception):
                report[d].append(dict(source=name, ok=False, error=str(got)[:120]))
            else:
                mine = [e for e in got if e['date'] == d and e['title']]
                events[d] += mine
                report[d].append(dict(source=name, ok=True, found=len(got), on_date=len(mine)))
    return events, report


def build_venues():
    shows = json.loads(get('https://api.todaytix.com/api/v2/shows?location=1&limit=500'))['data']
    slugs = sorted({s['venueUrl'] for s in shows if s.get('venueUrl')})
    V = tt_venues()
    todo = [s for s in slugs if not V.get(s)]
    with ThreadPoolExecutor(4) as ex:
        for slug, v in zip(todo, ex.map(lambda s: _safe(tt_venue_lookup, s), todo)):
            if v:
                V[slug] = v
    json.dump(V, open(TT_VENUES, 'w'), indent=0, sort_keys=True, ensure_ascii=False)
    print(len(slugs), 'venue slugs,', sum(1 for s in slugs if V.get(s)), 'with an address;', 'missing:',
          [s for s in slugs if not V.get(s)][:12])


if __name__ == '__main__':
    if '--build-venues' in sys.argv:
        build_venues()
    else:
        d = datetime.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.date.today()
        ev, rep = collect([d])
        for r in rep[d.isoformat()]:
            print(r)
        import collections
        print(len(ev[d.isoformat()]), 'events;', dict(collections.Counter(e['kind'] for e in ev[d.isoformat()])))
