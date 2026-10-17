#!/usr/bin/env python3
"""The day's picks: a short written plan for the day, drawn from the pulled listings and the quest list, with the
weather in mind.

    python3 picks.py list out 2026-10-17 [QUESTS_DIR]       print the weather, the day's events and the quests open
                                                             that day as numbered one-line candidates
    python3 picks.py build out 2026-10-17 CHOICES.json      write out/recs/2026-10-17.json

QUESTS_DIR holds the page database's quests and questlog collections as saved files (QUESTS_DIR/quests/*.json,
QUESTS_DIR/questlog/*.json). The choosing is done by whoever runs the pull (a scheduled Claude session). It writes
CHOICES.json as

    {"story": "paragraphs, separated by blank lines, naming each pick as [[the name as written|k]]",
     "picks": [{"n": 12, "why": "..."}, {"q": "dream-house", "why": "..."}, ...]}

where k counts the picks from 1, an "n" is an event number and a "q" a quest id. The page shows the story with each
[[name|k]] highlighted, and the pick's card when the pointer rests on it. A pick carries a copy of its event or quest,
so it still shows if a later pull drops or renames it. (A bare list of picks, the older form, still builds.)
"""
import datetime, glob, json, os, re, sys, urllib.request, zoneinfo

NY = zoneinfo.ZoneInfo('America/New_York')
MAX = 10
CARRY = ('title', 'time', 'until', 'venue', 'street', 'city', 'pinned', 'acts', 'url', 'source', 'kind', 'note', 'via', 'v')
QCARRY = ('id', 'title', 'theme', 'where', 'street', 'area', 'borough', 'cost', 'note', 'url', 'start', 'end', 'time', 'rule', 'cat',
          'lat', 'lon')
WD = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
# WMO weather codes, as Open-Meteo reports them
SKY = [(0, 'clear'), (1, 'mostly clear'), (2, 'partly cloudy'), (3, 'overcast'), (45, 'fog'), (48, 'fog'), (51, 'drizzle'),
       (53, 'drizzle'), (55, 'heavy drizzle'), (61, 'light rain'), (63, 'rain'), (65, 'heavy rain'), (66, 'freezing rain'),
       (67, 'freezing rain'), (71, 'light snow'), (73, 'snow'), (75, 'heavy snow'), (77, 'snow grains'), (80, 'showers'),
       (81, 'showers'), (82, 'heavy showers'), (85, 'snow showers'), (86, 'snow showers'), (95, 'thunderstorms'),
       (96, 'thunderstorms with hail'), (99, 'thunderstorms with hail')]


def load(out, date):
    day = json.load(open(os.path.join(out, 'days', date + '.json')))
    try:
        venues = json.load(open(os.path.join(out, 'routes', date + '.json'))).get('venues') or {}
    except (OSError, ValueError):
        venues = {}
    return day, venues


def best(r):
    """Quickest way there in minutes, and how."""
    opts = [(m['min'], k) for k, m in (r or {}).items() if m and m.get('min') is not None]
    return min(opts) if opts else (None, None)


def weather(date):
    """The day's forecast for Manhattan in four parts (morning, afternoon, evening, night), or None if unavailable."""
    try:
        url = ('https://api.open-meteo.com/v1/forecast?latitude=40.73&longitude=-73.99&hourly=temperature_2m,'
               'apparent_temperature,precipitation_probability,weather_code,wind_speed_10m&daily=sunset'
               '&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=America%2FNew_York&forecast_days=4')
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'blackmon'}), timeout=20) as r:
            d = json.load(r)
    except Exception:
        return None
    h = d['hourly']
    rows = [i for i, t in enumerate(h['time']) if t.startswith(date)]
    if not rows:
        return None
    sky = dict(SKY)
    parts = []
    for name, a, b in (('morning', 8, 12), ('afternoon', 12, 17), ('evening', 17, 22), ('night', 22, 24)):
        idx = [i for i in rows if a <= int(h['time'][i][11:13]) < b]
        if not idx:
            continue
        codes = [h['weather_code'][i] for i in idx]
        parts.append(dict(part=name, temp=round(sum(h['temperature_2m'][i] for i in idx) / len(idx)),
                          feels=round(min(h['apparent_temperature'][i] for i in idx)),
                          rain=max(h['precipitation_probability'][i] or 0 for i in idx),
                          wind=round(max(h['wind_speed_10m'][i] for i in idx)),
                          sky=sky.get(max(codes), 'mixed')))
    sunset = next((s[11:] for s in d['daily']['sunset'] if s.startswith(date)), None)
    return dict(parts=parts, sunset=sunset,
                line='; '.join(f"{p['part']} {p['temp']}°F {p['sky']}, rain {p['rain']}%, wind {p['wind']} mph" for p in parts)
                     + (f'; sunset {sunset}' if sunset else ''))


def quests(qdir, date):
    """The quests open on this date and not dropped or done, each with its own star."""
    if not qdir:
        return []
    items, log = [], {}
    for f in glob.glob(os.path.join(qdir, 'quests', '*.json')):
        d = json.load(open(f))
        items += (d.get('data') or d).get('items') or []
    for f in glob.glob(os.path.join(qdir, 'questlog', '*.json')):
        d = json.load(open(f))
        log[os.path.splitext(os.path.basename(f))[0]] = d.get('data') or d
    day = datetime.date.fromisoformat(date)
    wd = (day.weekday() + 1) % 7                 # the quests count Sunday as 0
    out = []
    for q in items:
        L = log.get(q.get('id')) or {}
        dropped = L['drop'] if 'drop' in L else q.get('cut')
        if dropped or (L.get('done') and q.get('cat') != 'recurring'):
            continue
        cat = q.get('cat')
        if cat in ('dated', 'seasonal') and not (q.get('start') and q['start'] <= date <= (q.get('end') or q['start'])):
            continue
        if cat == 'recurring' and (wd not in (q.get('weekdays') or []) or day.month not in (q.get('months') or range(1, 13))):
            continue
        out.append(dict(q, star=bool(L.get('star'))))
    return out


def home(out):
    try:
        return json.load(open(os.path.join(out, 'home.json')))
    except (OSError, ValueError):
        return None


def candidates(out, date, qdir=None):
    day, venues = load(out, date)
    h = home(out)
    d = datetime.date.fromisoformat(date)
    yield f"{WD[(d.weekday() + 1) % 7]} {date}{' (weekend: plan the day and the evening)' if d.weekday() >= 5 else ''}"
    w = weather(date)
    yield 'Weather: ' + (w['line'] if w else 'no forecast available')
    yield ''
    yield 'EVENTS'
    for n, e in enumerate(day['events']):
        if e.get('kind') == 'standing':
            continue
        mins, how = best(venues.get(e.get('v')))
        bits = [f"#{n}", e.get('time') or '--:--', e.get('kind') or 'other', e['title']]
        if e.get('acts'):
            bits.append('with ' + ', '.join(e['acts']))
        bits.append('@ ' + e.get('venue', '') + (f" ({e['city']})" if e.get('city') else ''))
        if mins is not None:
            bits.append(f'{mins} min by {how}')
        if e.get('pinned'):
            bits.append('saved venue')
        if e.get('source') in ('the skint', 'Skint'):
            bits.append('via the Skint')
        if e.get('note'):
            bits.append('· ' + e['note'][:90])
        yield ' | '.join(bits)
    qs = quests(qdir, date)
    if qs:
        yield ''
        yield 'QUESTS (the owner\'s own list of things to do this year; STARRED ones they most want)'
        for q in sorted(qs, key=lambda q: (not q['star'], q.get('cat') != 'dated', q.get('theme') or '')):
            when = {'dated': f"on now, until {q.get('end')}", 'seasonal': f"in season until {q.get('end')}",
                    'recurring': q.get('rule') or 'every week'}.get(q.get('cat'), 'any time')
            bits = [f"Q:{q['id']}", q.get('theme') or '', q['title'], '@ ' + ', '.join(x for x in (q.get('where'), q.get('area'), q.get('borough')) if x),
                    when + (f" {q['time']}" if q.get('time') else '')]
            if q.get('cost'):
                bits.append(q['cost'])
            if h and q.get('lat') is not None:
                import routes
                bits.append(f"{routes.km(h['lat'], h['lon'], q['lat'], q['lon']):.0f} km away")
            if q['star']:
                bits.append('STARRED')
            if q.get('note'):
                bits.append('· ' + q['note'][:140])
            yield ' | '.join(bits)


def route_quests(out, date, qpicks):
    """Travel times to the quests picked, added to the day's routes file under each one's venue key (as cloud.py does
    for events), so the page shows them on the quest's card. Quietly does nothing if routing fails."""
    h = home(out)
    if not (h and qpicks):
        return
    try:
        import routes, subway
        routes.fill(h, [(p['lat'], p['lon']) for p in qpicks])
        cache, profile = routes.cached(h), subway.profile_for(datetime.date.fromisoformat(date))
        path = os.path.join(out, 'routes', date + '.json')
        doc = json.load(open(path))
        for p in qpicks:
            v = routes.venue_key(p['lat'], p['lon'])
            r = cache.get(v)
            if r:
                sub, walk = r['subway'].get(profile), r['walk']
                if sub and walk and sub['min'] >= walk['min']:
                    sub = None
                doc['venues'][v] = dict(walk=walk, bike=r['bike'], subway=sub)
                p['v'] = v
        json.dump(doc, open(path, 'w'), ensure_ascii=False, separators=(',', ':'))
    except Exception as ex:
        print('could not route the quests:', ex, file=sys.stderr)


def build(out, date, choices):
    day, _ = load(out, date)
    got = json.load(open(choices))
    picked, story = (got, '') if isinstance(got, list) else (got.get('picks') or [], str(got.get('story') or '').strip())
    qall = {q['id']: q for q in quests(os.path.join(out, 'db'), date)} if os.path.isdir(os.path.join(out, 'db', 'quests')) else {}
    seen, picks, keep = set(), [], {}
    for i, c in enumerate(picked, 1):
        why = str(c.get('why') or '').strip()
        n, q = c.get('n'), c.get('q')
        if isinstance(n, int) and 0 <= n < len(day['events']) and day['events'][n].get('kind') != 'standing' and n not in seen and why:
            seen.add(n)
            e = day['events'][n]
            picks.append(dict({k: e[k] for k in CARRY if k in e}, why=why[:240]))
        elif isinstance(q, str) and q in qall and q not in seen and why:
            seen.add(q)
            picks.append(dict({k: qall[q][k] for k in QCARRY if qall[q].get(k)}, kind='quest', star=qall[q]['star'], why=why[:240]))
        else:
            print('skipped', c, file=sys.stderr)
            continue
        keep[i] = len(picks)
        if len(picks) == MAX:
            break
    # renumber the story's references to the picks that survived, and unlink any that did not
    def ref(m):
        k = keep.get(int(m.group(2)))
        return f'[[{m.group(1)}|{k}]]' if k else m.group(1)
    story = re.sub(r'\[\[([^|\]]+)\|(\d+)\]\]', ref, story)
    route_quests(out, date, [p for p in picks if p.get('kind') == 'quest' and p.get('lat') is not None])
    os.makedirs(os.path.join(out, 'recs'), exist_ok=True)
    doc = dict(date=date, made_at=datetime.datetime.now(NY).isoformat(timespec='seconds'), story=story[:6000],
               weather=weather(date), picks=picks)
    path = os.path.join(out, 'recs', date + '.json')
    json.dump(doc, open(path, 'w'), ensure_ascii=False, separators=(',', ':'))
    print(path, len(picks), 'picks,', len(re.findall(r'\[\[', story)), 'linked in the story')


if __name__ == '__main__':
    if len(sys.argv) >= 4 and sys.argv[1] == 'list':
        print('\n'.join(candidates(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None)))
    elif len(sys.argv) == 5 and sys.argv[1] == 'build':
        build(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        sys.exit(__doc__)
