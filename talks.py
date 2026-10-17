"""Readings, talks and gallery openings, for sources.collect. The readers are in talks_feeds.py; this places each
event at its own address (bookstores read in other stores and churches, galleries are everywhere) through the
city's geocoder, and says what kind of thing it is.

Gallery openings come from two listings, Artforum's artguide and Artsy, which overlap; fetch.py's same-time,
same-place check keeps one of each. Left out: the New School, NYPL, Center for Fiction and PEN (all behind bot
checks), Brooklyn Public Library (it answers a home connection but refuses the cloud pull's), and Caveat's talks,
which comedy.py already reads.

    python3 talks.py 2026-10-17
"""
import datetime, re, sys

import routes
import talks_feeds as F
from sources import NY, event

BOROUGHS = ('Manhattan', 'Brooklyn', 'Queens', 'Bronx', 'Staten Island')

# name, reader, kind
READERS = [
    ('Artforum artguide', F.artforum_artguide, 'art'), ('Artsy', F.artsy, 'art'),
    ('Strand Book Store', F.strand, 'talk'), ('Greenlight Bookstore', F.greenlight, 'talk'),
    ('The Twisted Spine', F.twisted_spine, 'talk'), ('McNally Jackson', F.mcnally_jackson, 'talk'),
    ('Books Are Magic', F.books_are_magic, 'talk'), ('Community Bookstore', F.community_bookstore, 'talk'),
    ('Astoria Bookshop', F.astoria_bookshop, 'talk'), ('POWERHOUSE Arena', F.powerhouse_arena, 'talk'),
    ('The Poetry Project', F.poetry_project, 'talk'),
    ('The Cooper Union', F.cooper_union, 'talk'),
]
# not for an adult evening out: story times, kids' events, online-only, store business
SKIP = r'book (club|group)|story ?time|\bkids?\b|children|toddler|baby|storytime|online|virtual|zoom|book swap|gift card|book club meeting'


# where a source's own events happen when it gives no street address ('in-store')
HOME = {'Astoria Bookshop': '36-19 30th St, Queens', 'Books Are Magic': '225 Smith St, Brooklyn',
        'Community Bookstore': '143 7th Ave, Brooklyn', 'POWERHOUSE Arena': '28 Adams St, Brooklyn'}


def split_address(name, address):
    """(store or room name, cleaned street address) from text like 'McNally Jackson Seaport, 4 Fulton St, New York',
    'Montague Store - 122 Montague St' or 'POWERHOUSE Arena, 28 Adams Street (Corner of ...), Brooklyn , NY'."""
    a = re.sub(r'\([^)]*\)', '', address or '')
    parts = [p.strip() for p in re.split(r',| - ', a) if p.strip() and not re.fullmatch(r'United States|USA', p.strip())]
    first = next((i for i, p in enumerate(parts) if re.match(r'\d', p)), None)
    if first is None:
        return name, HOME.get(name) if re.search(r'in-?store', address or '', re.I) or not address else None
    room = ' '.join(parts[:first]) or name
    return room, ', '.join(parts[first:])


def place(name, venue, address):
    """(name, street, borough, lat, lon) for an event, or None when it has no street address the city can find."""
    room, a = split_address(name, address)
    g = routes.geocode(a) if a else None
    if not g:
        return None
    borough = next((b for b in BOROUGHS if b in g['label']), 'Manhattan' if 'New York, NY' in g['label'] else '')
    if venue and venue != name:
        label = venue                                        # a gallery, from the listing
    elif room and room != name and len(room) < 60:
        label = room if name.split()[0].lower() in room.lower() else f'{name} at {room}'
    else:
        label = name
    return (label, a.split(',')[0].strip(), borough, g['lat'], g['lon'])


def items(d0, d1):
    """{source: [events] or the exception it raised}."""
    days = (datetime.date.fromisoformat(d1) - datetime.datetime.now(NY).date()).days + 1
    def one(r):
        name, f, kind = r
        try:
            out, seen = [], set()
            for e in f(max(days, 1)):
                day, t = e['start'].date().isoformat(), e['start'].strftime('%H:%M')
                notes = e.get('notes') or ''
                if not d0 <= day <= d1 or re.search(SKIP, f"{e['title']} {notes}", re.I) or (e['title'], day) in seen:
                    continue
                p = place(name, e['venue'], e.get('address'))
                if not p:
                    continue
                seen.add((e['title'], day))
                title = re.sub(r'^\s*\[?SOLD OUT\]?\s*-?\s*', '', e['title'], flags=re.I)
                note = 'sold out' if title != e['title'] else None
                if kind == 'art':
                    if re.search(r'opening reception', notes, re.I):
                        title = 'Opening: ' + title
                    until = re.search(r'until (\d\d:\d\d)', notes)
                    who = re.search(r'artists: ([^;]+)', notes)
                    note = ' · '.join(x for x in (who.group(1).strip() if who else '', f'reception until {until.group(1)}' if until else '') if x) or None
                elif '[offsite]' in title.lower():
                    title = re.sub(r'\[offsite\]\s*', '', title, flags=re.I)
                if t == '00:00' and 'time not given' in notes:
                    t = None
                out.append(event(p, title, day, t, e.get('link') or '', name, kind, note=note))
            return out
        except Exception as ex:
            return ex
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(6) as ex:
        return dict(zip((r[0] for r in READERS), ex.map(one, READERS)))


if __name__ == '__main__':
    d = sys.argv[1] if len(sys.argv) > 1 else datetime.datetime.now(NY).date().isoformat()
    d1 = sys.argv[2] if len(sys.argv) > 2 else d
    for name, got in items(d, d1).items():
        print(f'== {name}:', got if isinstance(got, Exception) else len(got))
        for e in ([] if isinstance(got, Exception) else sorted(got, key=lambda e: (e['date'], e['time'] or '')))[:4]:
            print('  ', e['date'], e['time'], e['venue'][:28], '|', e['street'][:22], e['city'], '|', e['title'][:50], '|', (e['note'] or '')[:40])
