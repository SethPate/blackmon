#!/usr/bin/env python3
"""Blackmon: tonight's events by time, with how long it takes to get there. Stdlib only.

    python3 server.py            http://127.0.0.1:8777

GET  /api/events?date=YYYY-MM-DD   the day's events with travel times from the saved home address
POST /api/home    {address}        change the home address (geocoded; routes are cached per home)
POST /api/refresh {date}           re-pull that day's events

Routes are filled in by a small background pool the first time a venue is seen from a home; the page polls
until `pending` is 0. Nothing here needs a browser session or a key.
"""
import datetime, json, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import fetch, routes, subway

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, 'config.json')
DEFAULT_HOME = 'City Hall Park, Manhattan'    # only used until config.json exists; the real address lives there, untracked
PORT = 8777

pool = ThreadPoolExecutor(2)
RETRY_AFTER = 120                        # seconds before a failed routing batch is tried again
lock = threading.Lock()
routing, failed, fetching = set(), {}, set()


def home():
    try:
        return json.load(open(CONFIG))['home']
    except (OSError, ValueError, KeyError):
        return set_home(DEFAULT_HOME)


def set_home(address):
    g = routes.geocode(address)
    if not g:
        return None
    h = dict(address=address, label=g['label'], lat=g['lat'], lon=g['lon'])
    json.dump(dict(home=h), open(CONFIG, 'w'), indent=1)
    return h


def _route_job(h, venues, key):
    try:
        routes.fill(h, venues)
        failed.pop(key, None)
    except Exception as ex:
        failed[key] = (str(ex)[:120], time.time())
    finally:
        with lock:
            routing.discard(key)


def _fetch_job(date):
    try:
        fetch.fetch(date)
    except Exception as ex:
        failed['fetch|' + date.isoformat()] = str(ex)[:120]
    finally:
        with lock:
            fetching.discard(date.isoformat())


def start_fetch(date):
    with lock:
        if date.isoformat() in fetching:
            return
        fetching.add(date.isoformat())
    pool.submit(_fetch_job, date)


def events(date):
    h = home()
    path = os.path.join(fetch.DATA, f'events-{date.isoformat()}.json')
    try:
        doc = json.load(open(path))
    except (OSError, ValueError):
        doc = dict(date=date.isoformat(), fetched_at=None, sources=[], events=[])
        if 'fetch|' + date.isoformat() not in failed:
            start_fetch(date)
    profile = subway.profile_for(date)
    cache = routes.cached(h)
    hk = routes.home_key(h)
    err = failed.get(hk)
    missing = []
    for e in doc['events']:
        r = cache.get(routes.venue_key(e['lat'], e['lon']))
        if r is None:
            missing.append((e['lat'], e['lon']))
            if err:
                e['route'] = dict(error=err[0])
            continue
        sub, walk = r['subway'].get(profile), r['walk']
        if sub and walk and sub['min'] >= walk['min']:
            sub = None                      # nobody takes the train to somewhere they can walk to sooner
        e['route'] = dict(walk=walk, bike=r['bike'], subway=sub)
    pending = 0
    if missing and not (err and time.time() - err[1] < RETRY_AFTER):
        pending = len(missing)
        with lock:
            if hk not in routing:
                routing.add(hk)
                pool.submit(_route_job, h, missing, hk)
    doc.update(home=h, profile=profile, pending=pending, fetching=date.isoformat() in fetching,
               today=fetch.today().isoformat(), fetch_error=failed.get('fetch|' + date.isoformat()))
    return doc


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _date(self, s):
        try:
            return datetime.date.fromisoformat(s)
        except (TypeError, ValueError):
            return fetch.today()

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == '/':
            body = open(os.path.join(HERE, 'index.html'), 'rb').read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)
        elif u.path == '/api/events':
            self._json(events(self._date(parse_qs(u.query).get('date', [None])[0])))
        else:
            self._json(dict(error='not found'), 404)

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
        except ValueError:
            return self._json(dict(error='bad json'), 400)
        if self.path == '/api/home':
            address = ' '.join(str(body.get('address', '')).split())
            try:
                h = set_home(address) if address else None
            except Exception as ex:
                return self._json(dict(error=f'address lookup failed: {ex}'), 502)
            if not h:
                return self._json(dict(error='could not find that address in NYC'), 422)
            self._json(dict(home=h))
        elif self.path == '/api/refresh':
            d = self._date(body.get('date'))
            failed.pop('fetch|' + d.isoformat(), None)
            start_fetch(d)
            self._json(dict(ok=True))
        else:
            self._json(dict(error='not found'), 404)


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    print(f'Blackmon on http://127.0.0.1:{port}  home: {home()["label"]}')
    ThreadingHTTPServer(('127.0.0.1', port), H).serve_forever()
