#!/usr/bin/env python3
"""Home -> venue travel times by mode, cached per home address. Stdlib only.

walk, bike   street-network times from the public Valhalla server run by FOSSGIS (valhalla1.openstreetmap.de),
             ferries switched off, asked for in batches: one call covers up to 90 venues
subway       subway.py's timetable model, with a street-network walk to the stations at the home end and a
             straight-line estimate at the venue end

Cache: cache/routes/<home lat,lon>.json, one entry per venue (keyed by its lat,lon to 5 places). A venue is
routed once per home and never again; changing the home address starts a new file and leaves the old one.
"""
import json, math, os, threading, time, urllib.error, urllib.parse, urllib.request

import subway

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'cache')
ROUTES = os.path.join(CACHE, 'routes')
GEOCODE = os.path.join(CACHE, 'geocode.json')
VALHALLA = 'https://valhalla1.openstreetmap.de'
BATCH = 90
UA = 'blackmon/0.1 (personal event list)'
STATION_KM = 1.1         # straight-line radius for candidate stations
STATION_MAX = 8
STATION_WALK_MAX = 22    # minutes on foot; further than this is not "the station near it"
_lock = threading.Lock()


_net_lock, _net_last = threading.Lock(), [0.0]
GAP = 1.2                # seconds between routing calls: it is a free public server


def _get(url, timeout=25):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def _load(path, default):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return default


def _save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    json.dump(obj, open(tmp, 'w'), indent=0)
    os.replace(tmp, path)


def matrix(costing, src, dests):
    """[(minutes, miles) or None] from src to each (lat, lon) in dests. One call at a time, spaced, with backoff."""
    out = []
    for i in range(0, len(dests), BATCH):
        body = json.dumps(dict(sources=[dict(lat=src[0], lon=src[1])],
                               targets=[dict(lat=la, lon=lo) for la, lo in dests[i:i + BATCH]],
                               costing=costing, units='miles', costing_options={costing: dict(use_ferry=0)})).encode()
        with _net_lock:
            for wait in (0, 5, 20):
                time.sleep(max(wait, _net_last[0] + GAP - time.time(), 0))
                try:
                    req = urllib.request.Request(VALHALLA + '/sources_to_targets', data=body,
                                                 headers={'User-Agent': UA, 'Content-Type': 'application/json'})
                    row = json.load(urllib.request.urlopen(req, timeout=60))['sources_to_targets'][0]
                    break
                except urllib.error.HTTPError as ex:
                    if ex.code not in (429, 502, 503, 504):
                        raise
                    err = ex
                except OSError as ex:
                    err = ex
                finally:
                    _net_last[0] = time.time()
            else:
                raise err
        out += [None if c.get('time') is None else (c['time'] / 60, c['distance']) for c in row]
    return out


def km(lat1, lon1, lat2, lon2):
    p = math.radians((lat1 + lat2) / 2)
    return math.hypot((lat2 - lat1) * 111.2, (lon2 - lon1) * 111.2 * math.cos(p))


def geocode(text):
    """NYC street address or place name -> dict(label, lat, lon), via the city's GeoSearch. None if not found."""
    key = ' '.join(text.lower().split())
    with _lock:
        cache = _load(GEOCODE, {})
    if key not in cache:
        d = _get('https://geosearch.planninglabs.nyc/v2/search?size=1&text=' + urllib.parse.quote(text))
        f = (d.get('features') or [None])[0]
        hit = None
        if f:
            lon, lat = f['geometry']['coordinates']
            p = f['properties']
            hit = dict(label=p.get('label', text), lat=lat, lon=lon, hood=p.get('neighbourhood') or p.get('borough') or '')
        with _lock:
            cache = _load(GEOCODE, {})
            cache[key] = hit
            _save(GEOCODE, cache)
    return cache[key]


def station_walks(lat, lon, routed=False):
    """{station_id: walk minutes} for the stations a person would actually walk to from this point.

    routed=True asks the street network for each candidate (used for the home end, once per home, where a
    wrong answer would skew every trip). Otherwise it is straight-line x 1.25 at 20 min/mile, the estimate
    an earlier project of mine spot-checked against real walks: fine at these
    distances except across water, and the one station close enough to a far shore to fool it is Roosevelt
    Island, which is only offered to points on the island."""
    st = subway.stations()
    near = sorted((km(lat, lon, v[1], v[2]), s) for s, v in st.items())
    near = [(d, s) for d, s in near if st[s][0] != 'Roosevelt Island' or d < 0.5]
    cand = [(d, s) for d, s in near if d <= STATION_KM][:STATION_MAX] or near[:3]
    walks = {s: d / 1.609 * 1.25 * 20 for d, s in cand}
    if routed:
        got = matrix('pedestrian', (lat, lon), [(st[s][1], st[s][2]) for _, s in cand])
        walks = {s: (g[0] if g else walks[s]) for (_, s), g in zip(cand, got)}
    keep = {s: round(w + 1, 1) for s, w in walks.items() if w <= STATION_WALK_MAX}
    return keep or {s: round(w + 1, 1) for s, w in sorted(walks.items(), key=lambda t: t[1])[:2]}


def home_key(home):
    return f"{home['lat']:.5f},{home['lon']:.5f}"


def venue_key(lat, lon):
    return f'{lat:.5f},{lon:.5f}'


def _path(home):
    return os.path.join(ROUTES, home_key(home) + '.json')


def cached(home):
    with _lock:
        return _load(_path(home), {})


def fill(home, venues):
    """Route every (lat, lon) in venues that this home has not seen yet. Returns how many were added."""
    with _lock:
        c = _load(_path(home), {})
    todo = sorted({(round(la, 5), round(lo, 5)) for la, lo in venues if venue_key(la, lo) not in c})
    hw = c.get('_home_stations')
    h = (home['lat'], home['lon'])
    if hw is None:
        hw = station_walks(*h, routed=True)
    if todo:
        walk, bike = matrix('pedestrian', h, todo), matrix('bicycle', h, todo)
    new = {}
    for i, (la, lo) in enumerate(todo):
        w, b = walk[i], bike[i]
        vw = station_walks(la, lo)
        new[venue_key(la, lo)] = dict(
            walk=w and dict(min=round(w[0]), mi=round(w[1], 1)),
            bike=b and dict(min=round(b[0]), mi=round(b[1], 1)),
            subway={p: subway.trip(hw, vw, p) for p in ('Weekday', 'Saturday', 'Sunday')})
    with _lock:
        c = _load(_path(home), {})
        c['_home'] = home
        c['_home_stations'] = hw
        c.update(new)
        _save(_path(home), c)
    return len(new)


if __name__ == '__main__':
    import sys
    home = geocode(sys.argv[1] if len(sys.argv) > 1 else 'City Hall Park, Manhattan')
    print(home)
    V = [('BAM', 40.6865, -73.9778), ('Village Vanguard', 40.7360, -74.0016), ('Culture Lab LIC', 40.7476, -73.9544)]
    fill(home, [(la, lo) for _, la, lo in V])
    c = cached(home)
    for name, la, lo in V:
        r = c[venue_key(la, lo)]
        s = r['subway']['Weekday']
        print(name, r['walk'], r['bike'], s and (s['min'], s['lines']))
