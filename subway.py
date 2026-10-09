#!/usr/bin/env python3
"""Subway travel times from the MTA's published timetable (GTFS), stdlib only.

    python3 subway.py            build cache/subway.json from cache/gtfs_subway.zip (downloads it if missing)

The graph is an EVENING one: only trips leaving a stop between 17:00 and 01:00 count, per service day
(Weekday / Saturday / Sunday). A ride edge is the median timetabled time between two consecutive stops on one
route in one direction; a transfer costs half the evening headway at that stop (capped) plus a minute of platform.
The first train is not waited for (see FIRST_WAIT); transfers are. It answers "door to door, about how long, on
which lines" -- it is a model, not a live trip planner: no delays, no service changes, no real-time.
"""
import csv, heapq, io, json, math, os, statistics, sys, urllib.request, zipfile
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'cache')
GTFS_URL = 'https://rrgtfsfeeds.s3.amazonaws.com/gtfs_subway.zip'
GTFS = os.path.join(CACHE, 'gtfs_subway.zip')
GRAPH = os.path.join(CACHE, 'subway.json')
WINDOW = (17 * 3600, 25 * 3600)
MIN_TRIPS = 6            # a stop pair served fewer times than this all evening is not a service you can plan on
MAX_WAIT = 12.0          # minutes; half-headway is capped here
PLATFORM = 1.0           # minutes added to every boarding after the first
FIRST_WAIT = 1.0         # minutes at the first platform: you leave home timed to a train, as any transit app assumes.
                         # Checked 2026-10-09 against 182 Google door-to-door times I had on file:
                         # charging half a headway here ran 6.8 min long on average; this runs 2.0 long (137 within 3 min), and what
                         # is left is evening transfer waits against Google's rush-hour ones (one-seat rides +1.3, transfers +2.8).
SHUTTLES = {'GS': 'S', 'FS': 'S', 'H': 'S', 'SI': 'SIR'}


def line_name(route_id):
    return SHUTTLES.get(route_id) or (route_id[:-1] if route_id.endswith('X') and len(route_id) > 1 else route_id)


def _secs(t):
    h, m, s = t.split(':')
    return int(h) * 3600 + int(m) * 60 + int(s)


def build():
    os.makedirs(CACHE, exist_ok=True)
    if not os.path.exists(GTFS):
        urllib.request.urlretrieve(GTFS_URL, GTFS)
    z = zipfile.ZipFile(GTFS)
    rows = lambda name: csv.DictReader(io.TextIOWrapper(z.open(name), 'utf-8-sig'))

    parent, stations = {}, {}
    for r in rows('stops.txt'):
        if r.get('parent_station'):
            parent[r['stop_id']] = r['parent_station']
        else:
            stations[r['stop_id']] = [r['stop_name'], float(r['stop_lat']), float(r['stop_lon'])]
    trips = {r['trip_id']: (r['route_id'], r['service_id'], r['direction_id']) for r in rows('trips.txt')}

    seg = defaultdict(list)      # (service, route, dir, a, b) -> [seconds]
    last = None
    for r in rows('stop_times.txt'):
        tid = r['trip_id']
        st = parent.get(r['stop_id'], r['stop_id'])
        dep, arr = _secs(r['departure_time']), _secs(r['arrival_time'])
        if last and last[0] == tid and WINDOW[0] <= last[2] < WINDOW[1]:
            route, service, d = trips[tid]
            seg[(service, route, d, last[1], st)].append(arr - last[2])
        last = (tid, st, dep)

    hours = (WINDOW[1] - WINDOW[0]) / 3600
    profiles = {}
    for (service, route, d, a, b), ts in seg.items():
        if len(ts) < MIN_TRIPS:
            continue
        wait = min(hours * 60 / len(ts) / 2, MAX_WAIT)
        profiles.setdefault(service, []).append([route, d, a, b, round(statistics.median(ts) / 60, 2), round(wait, 2)])
    transfers = [[r['from_stop_id'], r['to_stop_id'], int(r['min_transfer_time'] or 180) / 60]
                 for r in rows('transfers.txt') if r['from_stop_id'] != r['to_stop_id']]
    feed = next(rows('feed_info.txt'), {})
    json.dump(dict(feed=feed.get('feed_version', ''), stations=stations, profiles=profiles, transfers=transfers),
              open(GRAPH, 'w'))
    return GRAPH


_G = {}


def graph(profile):
    """Adjacency for one service day. Nodes are station ids ('635') and platforms ('635|6|1')."""
    if profile in _G:
        return _G[profile]
    if not os.path.exists(GRAPH):
        build()
    raw = _G.get('raw') or json.load(open(GRAPH))
    _G['raw'] = raw
    adj = defaultdict(list)
    for route, d, a, b, mins, wait in raw['profiles'][profile]:
        pa, pb = f'{a}|{route}|{d}', f'{b}|{route}|{d}'
        adj[pa].append((pb, mins))
        if not any(n == pa for n, _ in adj[a]):
            adj[a].append((pa, wait + PLATFORM))
        if not any(n == b for n, _ in adj[pb]):
            adj[pb].append((b, 0.0))
    for a, b, mins in raw['transfers']:
        adj[a].append((b, mins))
    _G[profile] = (adj, raw['stations'])
    return _G[profile]


def stations():
    if not os.path.exists(GRAPH):
        build()
    raw = _G.get('raw') or json.load(open(GRAPH))
    _G['raw'] = raw
    return raw['stations']


def profile_for(date):
    """date: datetime.date -> 'Weekday' | 'Saturday' | 'Sunday'."""
    return ('Weekday', 'Weekday', 'Weekday', 'Weekday', 'Weekday', 'Saturday', 'Sunday')[date.weekday()]


def trip(origin_walks, dest_walks, profile):
    """origin_walks / dest_walks: {station_id: walk minutes}. Returns the fastest door-to-door subway trip:
    dict(min, lines=['7','G'], legs=[{line, board, alight}], walk_a, walk_b) or None."""
    adj, st = graph(profile)
    dist, prev, heap = {}, {}, []
    for s, w in origin_walks.items():
        dist[s] = w
        prev[s] = None
        heapq.heappush(heap, (w, s))
    for s, w in origin_walks.items():
        for p, _ in adj.get(s, ()):
            if '|' in p and w + FIRST_WAIT < dist.get(p, math.inf):
                dist[p] = w + FIRST_WAIT
                prev[p] = s
                heapq.heappush(heap, (dist[p], p))
    best, best_s, done = math.inf, None, set()
    while heap:
        d, n = heapq.heappop(heap)
        if n in done:
            continue
        done.add(n)
        if d >= best:
            break
        if n in dest_walks and prev[n] is not None and d + dest_walks[n] < best:
            best, best_s = d + dest_walks[n], n
        for m, w in adj.get(n, ()):
            nd = d + w
            if nd < dist.get(m, math.inf):
                dist[m] = nd
                prev[m] = n
                heapq.heappush(heap, (nd, m))
    if best_s is None:
        return None
    path, n = [], best_s
    while n is not None:
        path.append(n)
        n = prev[n]
    path.reverse()
    legs = []
    for n in path:
        if '|' not in n:
            continue
        sid, route, _ = n.split('|')
        ln = line_name(route)
        if legs and legs[-1]['_r'] == route:
            legs[-1]['alight'] = st[sid][0]
        else:
            legs.append(dict(line=ln, board=st[sid][0], alight=st[sid][0], _r=route))
    for l in legs:
        del l['_r']
    lines = [l['line'] for l in legs]
    return dict(min=round(best), lines=lines, legs=legs,
                walk_a=round(origin_walks[path[0]]), walk_b=round(dest_walks[best_s]))


if __name__ == '__main__':
    p = build()
    raw = json.load(open(p))
    print('wrote', p, {k: len(v) for k, v in raw['profiles'].items()}, 'stations', len(raw['stations']))
