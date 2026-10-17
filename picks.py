#!/usr/bin/env python3
"""The day's picks: a short list chosen from the pulled listings, each with a line on why.

    python3 picks.py list out 2026-10-17                    print the day's events as numbered one-line candidates
    python3 picks.py build out 2026-10-17 CHOICES.json      write out/recs/2026-10-17.json from the chosen numbers

The choosing is done by whoever runs the pull (a scheduled Claude session): it reads the list, picks a handful and
writes CHOICES.json as [{"n": 12, "why": "..."}, ...] in the order it wants them shown. The page reads the result as
recs/<date>. A pick carries a copy of its event, so it still shows if a later pull drops or renames that event.
"""
import datetime, json, os, sys, zoneinfo

NY = zoneinfo.ZoneInfo('America/New_York')
MAX = 8
CARRY = ('title', 'time', 'until', 'venue', 'street', 'city', 'pinned', 'acts', 'url', 'source', 'kind', 'note', 'via', 'v')


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


def candidates(out, date):
    day, venues = load(out, date)
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


def build(out, date, choices):
    day, _ = load(out, date)
    picked = json.load(open(choices))
    if not isinstance(picked, list):
        sys.exit('choices must be a JSON list of {"n": number, "why": text}')
    seen, picks = set(), []
    for c in picked:
        n, why = c.get('n'), str(c.get('why') or '').strip()
        if not isinstance(n, int) or not 0 <= n < len(day['events']) or n in seen or not why \
                or day['events'][n].get('kind') == 'standing':
            print('skipped', c, file=sys.stderr)
            continue
        seen.add(n)
        e = day['events'][n]
        picks.append(dict({k: e[k] for k in CARRY if k in e}, why=why[:240]))
        if len(picks) == MAX:
            break
    os.makedirs(os.path.join(out, 'recs'), exist_ok=True)
    doc = dict(date=date, made_at=datetime.datetime.now(NY).isoformat(timespec='seconds'), picks=picks)
    path = os.path.join(out, 'recs', date + '.json')
    json.dump(doc, open(path, 'w'), ensure_ascii=False, separators=(',', ':'))
    print(path, len(picks), 'picks')


if __name__ == '__main__':
    if len(sys.argv) >= 4 and sys.argv[1] == 'list':
        print('\n'.join(candidates(sys.argv[2], sys.argv[3])))
    elif len(sys.argv) == 5 and sys.argv[1] == 'build':
        build(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        sys.exit(__doc__)
