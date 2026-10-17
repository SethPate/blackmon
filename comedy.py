"""Comedy clubs and the comedy nights at mixed rooms, for sources.collect. The readers are in comedy_feeds.py; this
places each show at its room, takes the lineup out of the notes into the acts, and sorts out the mixed rooms.

UCB and The Stand are behind Cloudflare and are not read. The Bell House is read by fetch.py already.

    python3 comedy.py 2026-10-17
"""
import datetime, re, sys

import comedy_feeds as F
from sources import NY, event

P = {
    'cellar': ('Comedy Cellar', '117 MacDougal St.', 'Manhattan', 40.73019, -74.00056),
    'underground': ('Comedy Cellar at the Village Underground', '130 W. 3rd St.', 'Manhattan', 40.73067, -74.00081),
    'caveat': ('Caveat', '21A Clinton St.', 'Manhattan', 40.72067, -73.98437),
    'unionhall': ('Union Hall', '702 Union St.', 'Brooklyn', 40.67604, -73.98009),
    'littlefield': ('Littlefield', '635 Sackett St.', 'Brooklyn', 40.67848, -73.98337),
    'gotham': ('Gotham Comedy Club', '208 W. 23rd St.', 'Manhattan', 40.74413, -73.99644),
    'nycc': ('New York Comedy Club', '241 E. 24th St.', 'Manhattan', 40.73892, -73.98080),
    'nycc_ev': ('New York Comedy Club East Village', '85 E. 4th St.', 'Manhattan', 40.72658, -73.98980),
    'nycc_uws': ('New York Comedy Club Upper West Side', '236 W. 78th St.', 'Manhattan', 40.78280, -73.98017),
    'comicstrip': ('Comic Strip Live', '1568 Second Ave.', 'Manhattan', 40.77485, -73.95369),
    'grisly': ('The Grisly Pear', '107 MacDougal St.', 'Manhattan', 40.72984, -74.00081),
    'grisly_mid': ('The Grisly Pear Midtown', '243 W. 54th St.', 'Manhattan', 40.76453, -73.98332),
    'eastville': ('Eastville Comedy Club', '487 Atlantic Ave.', 'Brooklyn', 40.68590, -73.98161),
    'rodneys': ("Rodney's Comedy Club", '1118 First Ave.', 'Manhattan', 40.76104, -73.96062),
    'tinycup': ('The Tiny Cupboard', '10 Cooper St.', 'Brooklyn', 40.68369, -73.91121),
    'bcc': ('Brooklyn Comedy Collective', '167 Graham Ave.', 'Brooklyn', 40.70772, -73.94349),
    'bcc2': ('Brooklyn Comedy Collective (Boerum St.)', '144 Boerum St.', 'Brooklyn', 40.70584, -73.94263),
    'magnet': ('Magnet Theater', '254 W. 29th St.', 'Manhattan', 40.74877, -73.99535),
    'pit': ('The PIT', '154 W. 29th St.', 'Manhattan', 40.74735, -73.99229),
    'asylum': ('Asylum NYC', '123 E. 24th St.', 'Manhattan', 40.74062, -73.98467),
    'gvcc': ('Greenwich Village Comedy Club', '99 MacDougal St.', 'Manhattan', 40.72965, -74.00109),
    'westside': ('West Side Comedy Club', '201 W. 75th St.', 'Manhattan', 40.78081, -73.98051),
    'bond45': ('Stand Up NY at Bond 45', '221 W. 46th St.', 'Manhattan', 40.75923, -73.98631),
    'edison': ('Stand Up NY at the Hotel Edison', '228 W. 47th St.', 'Manhattan', 40.75964, -73.98629),
    'qed': ('QED Astoria', '27-16 23rd Ave.', 'Queens', 40.77554, -73.91494),
    'ethels': ("Young Ethel's", '506 Fifth Ave.', 'Brooklyn', 40.66722, -73.98830),
    'cumming': ('Club Cumming', '505 E. 6th St.', 'Manhattan', 40.72539, -73.98337),
    'petes': ("Pete's Candy Store", '709 Lorimer St.', 'Brooklyn', 40.71809, -73.95028),
}

COMEDY = r'comed|stand-?up|improv|sketch|roast|\bmic\b|clown|funny|jokes?\b'
TALK = r'lecture|\btalk\b|science|conversation|book club|reading|quiz|trivia|storytell|poet'
THEATER = r'theat|\bplay\b|musical|presents:'
SKIP = r'\bclass(es)?\b|workshop|\bintensive\b|\b101\b|gift card|private event'


def room(e, default, rooms):
    """The place key for a show at a club with several rooms: the first (pattern, key) found in its venue or notes."""
    text = f"{e.get('venue')} {e.get('notes')}"
    return next((k for pat, k in rooms if re.search(pat, text, re.I)), default)


def kind(e, mixed):
    """A comedy club's show is comedy. At a mixed room, say what it is from its title, or leave it out (None)."""
    if not mixed:
        return 'comedy'
    t = e['title'] or ''                    # the title only: these readers' notes describe the room, not the show
    if re.search(COMEDY, t, re.I):
        return 'comedy'
    if re.search(TALK, t, re.I):
        return 'talk'
    if re.search(THEATER, t, re.I):
        return 'theater'
    return mixed if mixed is not True else None


# reader, default place, rooms, and for a mixed room the kind of anything that is not comedy or a talk (True: drop it)
READERS = [
    ('Comedy Cellar', F.fetch_comedy_cellar, 'cellar', [(r'Underground|Pussycat', 'underground')], False),
    ('Caveat', F.fetch_caveat, 'caveat', [], 'other'),
    ('Union Hall', F.fetch_union_hall, 'unionhall', [], 'comedy'),
    ('Littlefield', F.fetch_littlefield, 'littlefield', [], 'music'),
    ('Gotham Comedy Club', F.fetch_gotham, 'gotham', [], False),
    ('New York Comedy Club', F.fetch_new_york_comedy_club, 'nycc', [(r'85 E|East Village|4th St', 'nycc_ev'), (r'78th|Upper West', 'nycc_uws')], False),
    ('Comic Strip Live', F.fetch_comic_strip, 'comicstrip', [], False),
    ('The Grisly Pear', F.fetch_grisly_pear, 'grisly', [(r'54th|Midtown', 'grisly_mid')], False),
    ('Eastville Comedy Club', F.fetch_eastville, 'eastville', [], False),
    ("Rodney's Comedy Club", F.fetch_rodneys, 'rodneys', [], False),
    ('The Tiny Cupboard', F.fetch_tinycupboard, 'tinycup', [], False),
    ('Brooklyn Comedy Collective', F.fetch_bcc, 'bcc', [(r'Boerum', 'bcc2')], False),
    ('Magnet Theater', F.fetch_magnet, 'magnet', [], False),
    ('The PIT', F.fetch_pit, 'pit', [], False),
    ('Asylum NYC', F.fetch_asylum, 'asylum', [], 'theater'),
    ('Greenwich Village Comedy Club', F.fetch_gvcc, 'gvcc', [], False),
    ('West Side Comedy Club', F.fetch_westside, 'westside', [], False),
    ('Stand Up NY', F.fetch_standupny, 'bond45', [(r'Edison', 'edison')], False),
    ('QED Astoria', F.fetch_qed, 'qed', [], 'comedy'),
    ("Young Ethel's", F.fetch_youngethels, 'ethels', [], False),
    ('Club Cumming', F.fetch_clubcumming, 'cumming', [], 'other'),
    ("Pete's Candy Store", F.fetch_petes, 'petes', [], False),
]


def acts_and_note(notes):
    m = re.search(r'lineup:\s*([^;|]+)', notes or '', re.I)
    names = [n.strip() for n in m.group(1).split(',') if n.strip()] if m else []
    sold = 'sold out' if re.search(r'sold out', notes or '', re.I) else None
    return names, sold


def shows(d0, d1):
    """{venue: [events] or the exception it raised}."""
    days = (datetime.date.fromisoformat(d1) - datetime.datetime.now(NY).date()).days + 1
    def one(r):
        name, f, home, rooms, mixed = r
        try:
            out, seen = [], set()
            for e in f(max(days, 1)):
                day, t = e['start'].date().isoformat(), e['start'].strftime('%H:%M')
                k = kind(e, mixed)
                if not (d0 <= day <= d1) or not k or re.search(SKIP, e['title'] or '', re.I) or (e['title'], day, t) in seen:
                    continue
                seen.add((e['title'], day, t))
                names, sold = acts_and_note(e.get('notes'))
                title = e['title']
                if name == 'Comedy Cellar':
                    title = 'Comedy Cellar: ' + re.sub(r'^Comedy Cellar:\s*', '', title)
                out.append(event(P[room(e, home, rooms)], title, day, t, e.get('link') or '', name, k, names, sold))
            return out
        except Exception as ex:
            return ex
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(6) as ex:
        return dict(zip((r[0] for r in READERS), ex.map(one, READERS)))


if __name__ == '__main__':
    d = sys.argv[1] if len(sys.argv) > 1 else datetime.datetime.now(NY).date().isoformat()
    for name, got in shows(d, d).items():
        print(f'== {name}:', got if isinstance(got, Exception) else len(got))
        for e in ([] if isinstance(got, Exception) else sorted(got, key=lambda e: e['time']))[:3]:
            print('  ', e['time'], e['kind'], e['venue'][:30], '|', e['title'][:45], '|', ', '.join(e['acts'])[:50])
