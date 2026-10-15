#!/usr/bin/env python3
"""Non-concert sources: theater, dance, opera, film and the fringe houses. Stdlib only.

    python3 sources.py 2026-10-10            print what each source gives for a day
    python3 sources.py --build-venues        refresh tt_venues.json (addresses of TodayTix venues)

Most of these read a ticketing system rather than a venue's web page, because one reader then covers every
house that sells through it:

  OvationTix   La MaMa, Performance Space New York, Abrons, The Bushwick Starr, The Brick, Danspace Project,
               Roulette, Dixon Place, Nuyorican Poets Cafe, and the Off-Broadway rental houses SoHo Playhouse,
               Theater for the New City, The Players Theatre, The Flea, Target Margin, The Wild Project, WP Theater,
               York Theatre, Baryshnikov Arts, New Ohio
  Spektrix     St. Ann's Warehouse, New York Theatre Workshop, PAC NYC, Soho Rep, 59E59, Irish Rep, Vineyard,
               Atlantic, MCC, Signature, The New Group, Classic Stage, Theatre for a New Audience.
               Always through system.spektrix.com: the cloud pull's network refuses houses' own tickets.* names.
  TodayTix     Broadway and Off-Broadway plays and musicals, the Met, City Center and others (about 300 shows).
               Only the shows whose producers list there: a rental house runs many more, hence the houses above.
  BAM          its own calendar feed, which includes the cinemas
  DICE         Saint Vitus Bar, from the listing feed behind the show list on its own site
  and three single houses: Wonderville, the Village Vanguard, NYC Next Level (fighting-game weeklies)
  Screen Slate  repertory and arthouse cinema listings, kept to a short list of houses
  Fandango      one multiplex, the Regal at Kaufman Astoria

collect(dates) fetches each source once for the whole date range and returns events grouped by day, plus a
report line per source and day so a source that silently returns nothing is visible on the page.
"""
import datetime, gzip, html, json, os, re, sys, urllib.parse, urllib.request, zoneinfo
from concurrent.futures import ThreadPoolExecutor

import routes

HERE = os.path.dirname(os.path.abspath(__file__))
NY = zoneinfo.ZoneInfo('America/New_York')
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
    'sohoph':   ('SoHo Playhouse', '15 Vandam St.', 'Manhattan', 40.72655, -74.00436),
    'tnc':      ('Theater for the New City', '155 First Ave.', 'Manhattan', 40.72881, -73.98529),
    'players':  ('The Players Theatre', '115 MacDougal St.', 'Manhattan', 40.73020, -74.00072),
    'flea':     ('The Flea', '20 Thomas St.', 'Manhattan', 40.71607, -74.00603),
    'tmargin':  ('Target Margin', '232 52nd St.', 'Brooklyn', 40.64727, -74.01738),
    '59e59':    ('59E59 Theaters', '59 E. 59th St.', 'Manhattan', 40.76341, -73.97038),
    'irishrep': ('Irish Repertory Theatre', '132 W. 22nd St.', 'Manhattan', 40.74263, -73.99477),
    'vineyard': ('Vineyard Theatre', '108 E. 15th St.', 'Manhattan', 40.73467, -73.98916),
    'atlantic': ('Atlantic Theater Company', '336 W. 20th St.', 'Manhattan', 40.74387, -74.00158),
    'mcc':      ('MCC Theater', '511 W. 52nd St.', 'Manhattan', 40.76661, -73.99124),
    'signature': ('Signature Theatre', '480 W. 42nd St.', 'Manhattan', 40.75905, -73.99508),
    'newgroup': ('The New Group', '480 W. 42nd St.', 'Manhattan', 40.75905, -73.99508),   # plays at the Signature Center
    'csc':      ('Classic Stage Company', '136 E. 13th St.', 'Manhattan', 40.73265, -73.98838),
    'tfana':    ('Theatre for a New Audience', '262 Ashland Pl.', 'Brooklyn', 40.68745, -73.97880),
    'wild':     ('The Wild Project', '195 E. 3rd St.', 'Manhattan', 40.72306, -73.98328),
    'wp':       ('WP Theater', '2162 Broadway', 'Manhattan', 40.78181, -73.98054),
    'york':     ('York Theatre Company', '150 E. 76th St.', 'Manhattan', 40.77318, -73.96127),
    'bac':      ('Baryshnikov Arts', '450 W. 37th St.', 'Manhattan', 40.75606, -73.99730),
    'newohio':  ('New Ohio Theatre', '154 Christopher St.', 'Manhattan', 40.73226, -74.00817),
    'bam':      ('BAM', '30 Lafayette Ave.', 'Brooklyn', 40.68650, -73.97780),
    'nuyorican': None,           # the cafe is dark for renovation and its nights move around; each one is placed by its ticket page
    'wonderville': ('Wonderville', '1186 Broadway', 'Brooklyn', 40.69189, -73.92808),
    'vanguard': ('Village Vanguard', '178 Seventh Ave. South', 'Manhattan', 40.73604, -74.00162),
    'vitus':    ('Saint Vitus Bar', '428 Troutman St.', 'Brooklyn', 40.70716, -73.92200),
}
# Cinemas read from Screen Slate, by the name it uses for each. A short list on purpose: the houses the city is
# known for, not every screen. BAM is left out here because its own feed above already covers it.
CINEMAS = {
    'Film Forum': ('Film Forum', '209 W. Houston St.', 'Manhattan', 40.72822, -74.00449),
    'Metrograph': ('Metrograph', '7 Ludlow St.', 'Manhattan', 40.71511, -73.99117),
    'IFC Center': ('IFC Center', '323 Sixth Ave.', 'Manhattan', 40.73123, -74.00167),
    'Film at Lincoln Center': ('Film at Lincoln Center', '165 W. 65th St.', 'Manhattan', 40.77426, -73.98426),
    'Anthology Film Archives': ('Anthology Film Archives', '32 Second Ave.', 'Manhattan', 40.72468, -73.99012),
    'Paris Theater': ('Paris Theater', '4 W. 58th St.', 'Manhattan', 40.76375, -73.97432),
    'Museum of Modern Art': ('Museum of Modern Art', '11 W. 53rd St.', 'Manhattan', 40.76119, -73.97701),
    'Museum of the Moving Image': ('Museum of the Moving Image', '36-01 35th Ave.', 'Queens', 40.75630, -73.92392),
    'Nitehawk Cinema Williamsburg': ('Nitehawk Williamsburg', '136 Metropolitan Ave.', 'Brooklyn', 40.71599, -73.96259),
    'Nitehawk Cinema Prospect Park': ('Nitehawk Prospect Park', '188 Prospect Park West', 'Brooklyn', 40.66163, -73.97985),
    'Spectacle': ('Spectacle', '124 S. 3rd St.', 'Brooklyn', 40.71248, -73.96285),
}
REGAL_ASTORIA = ('Regal UA Kaufman Astoria', '35-30 38th St.', 'Queens', 40.75426, -73.92416)
OVATION = [('lamama', 42, 'theater'), ('psny', 203, 'theater'), ('abrons', 209, 'theater'), ('starr', 34289, 'theater'),
           ('brick', 122, 'theater'), ('danspace', 2742, 'dance'), ('roulette', 36368, 'music'), ('dixon', 35526, 'theater'),
           ('nuyorican', 35133, 'talk'), ('sohoph', 35583, 'theater'), ('tnc', 35441, 'theater'),
           ('players', 277, 'theater'), ('flea', 14, 'theater'), ('tmargin', 282, 'theater'), ('wild', 621, 'theater'),
           ('wp', 34655, 'theater'), ('york', 34375, 'theater'), ('bac', 31295, 'other'), ('newohio', 34708, 'theater')]
OVATION_NAMES = {'nuyorican': 'Nuyorican Poets Cafe'}
SPEKTRIX = [('stanns', 'https://system.spektrix.com/stannswarehouse', 'https://stannswarehouse.org/'),
            ('nytw', 'https://tickets.nytw.org/newyorktheatreworkshop', 'https://www.nytw.org/'),
            ('pac', 'https://tickets.pacnyc.org/pacnyc', 'https://pacnyc.org/whats-on/'),
            ('sohorep', 'https://system.spektrix.com/sohorep', 'https://sohorep.org/'),
            ('59e59', 'https://system.spektrix.com/59e59', 'https://59e59.org/'),
            ('irishrep', 'https://system.spektrix.com/irishrep', 'https://irishrep.org/'),
            ('vineyard', 'https://system.spektrix.com/vineyardtheatre', 'https://vineyardtheatre.org/'),
            ('atlantic', 'https://system.spektrix.com/atlantictheatercompany', 'https://atlantictheater.org/'),
            ('mcc', 'https://system.spektrix.com/mcc', 'https://mcctheater.org/'),
            ('signature', 'https://system.spektrix.com/signaturetheatre', 'https://www.signaturetheatre.org/'),
            ('newgroup', 'https://system.spektrix.com/thenewgroup', 'https://thenewgroup.org/'),
            ('csc', 'https://system.spektrix.com/classicstage', 'https://www.classicstage.org/'),
            ('tfana', 'https://system.spektrix.com/tfana', 'https://www.tfana.org/')]
# place key, source name, and the partner key and promoter names the house's own page hands to DICE's list widget
DICE = [('vitus', 'Saint Vitus', '1RsJ9u1HnFaj5F5hqFD7F9Idwsqi0o4z7QMQ2uGw',
         ['Saint Vitus LLC (dba Saint Vitus Bar)', 'SV Cathedral LLC'])]
DICE_KINDS = [('music', 'music'), ('theatre', 'theater'), ('film', 'film'), ('comedy', 'comedy'), ('talk', 'talk')]
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


def event(place, title, date, time, url, source, kind, acts=(), note=None):
    name, street, city, lat, lon = place
    return dict(note=clean(note) or None, title=clean(title), date=date, time=time or None, venue=name, street=street, city=city, lat=lat,
                lon=lon, acts=[clean(a) for a in acts if a and clean(a)][:3], url=url, source=source, kind=kind)


def ovation_room(client, production_id, default, default_kind):
    """(place, kind) for one production, from its ticket page. Place: several of these houses use more than one
    room, and one of them has no home at the moment; falls back to the house's own address. Kind: the house's
    default unless the description calls it stand-up or its maker a comedian, since the rental houses mix
    comedians' hours in with plays and OvationTix has no genre."""
    kind = default_kind
    try:
        prod = json.loads(get(f'https://web.ovationtix.com/trs/api/rest/Production({production_id})',
                              {'clientId': str(client), 'newCIRequest': 'true'}))
        if re.search(r'\bstand-?up\b|\bcomedians?\b', clean(prod.get('description')), re.I):
            kind = 'comedy'
        v = prod.get('venue') or {}
        a = v.get('address') or {}
        if re.search(r'online|zoom|virtual|livestream', f"{a.get('line1')} {v.get('name')}", re.I):
            return None, kind
        if a.get('line1'):
            g = routes.geocode(f"{a['line1']}, {a.get('city') or 'New York'}, NY {a.get('zipcode') or ''}")
            if g and (default is None or routes.km(g['lat'], g['lon'], default[3], default[4]) < 25):
                city = 'Manhattan' if (a.get('city') or '').strip() == 'New York' else (a.get('city') or '').strip()
                return (clean(v.get('name')) or (default and default[0]), a['line1'].strip(), city, g['lat'], g['lon']), kind
    except Exception:
        pass
    return default, kind


def ovationtix(d0, d1):
    out = {}
    for key, client, kind in OVATION:
        house = PLACES[key]
        label = house[0] if house else OVATION_NAMES[key]
        try:
            days = json.loads(get(f'https://web.ovationtix.com/trs/api/rest/CalendarProductions?startDate={d0}&endDate={d1}',
                                  {'clientId': str(client), 'newCIRequest': 'true'}))
            rows, found = [], 0
            for day in days:
                for p in day.get('productions') or []:
                    name = re.sub(r'^\d{4}/\d\d/\d\d\s+', '', p.get('name') or '')
                    low = name.lower()
                    if p.get('hidden') or 'livestream' in low or '[livestr' in low or 'online' in low or 'virtual' in low:
                        continue
                    for s in p.get('showtimes') or []:
                        t = s.get('performanceStartTime') or ''
                        if s.get('isCancelled') or s.get('isVisible') is False or len(t) < 16:
                            continue
                        found += 1
                        if d0 <= t[:10] <= d1:
                            rows.append((p.get('productionId'), name, t, p.get('subtitle')))
            rooms = {pid: ovation_room(client, pid, house, kind) for pid in {r[0] for r in rows}}
            evs = [event(rooms[pid][0], name, t[:10], t[11:16], f'https://ci.ovationtix.com/{client}/production/{pid}',
                         label, rooms[pid][1], [sub]) for pid, name, t, sub in rows if rooms[pid][0]]
            out[label] = Found(evs, found)
        except Exception as ex:
            out[label] = ex
    return out


class Found(list):
    """A source's events for the requested days, remembering how many it lists in all."""
    def __init__(self, items, total):
        super().__init__(items)
        self.total = total


def wonderville(d0, d1):
    place = PLACES['wonderville']
    try:
        d = json.loads(get('https://www.wonderville.nyc/events?format=json'))
        evs = []
        for e in d.get('upcoming') or []:
            if not e.get('startDate'):
                continue
            t = datetime.datetime.fromtimestamp(e['startDate'] / 1000, NY)
            evs.append(event(place, e.get('title'), t.date().isoformat(), t.strftime('%H:%M'),
                             'https://www.wonderville.nyc' + (e.get('fullUrl') or '/events'), 'Wonderville', 'other'))
        return {'Wonderville': evs}
    except Exception as ex:
        return {'Wonderville': ex}


def startgg(d0, d1):
    """NYC Next Level's fighting-game weeklies. start.gg's own site API; tournaments appear a week or so ahead."""
    try:
        q = ('query($slug:String){hub(slug:$slug){tournaments(query:{perPage:15}){nodes'
             '{name slug startAt venueName venueAddress city lat lng isOnline}}}}')
        body = json.dumps(dict(query=q, variables=dict(slug='nyc-next-level'))).encode()
        req = urllib.request.Request('https://www.start.gg/api/-/gql', data=body, headers={
            'User-Agent': UA, 'Content-Type': 'application/json', 'client-version': '20'})
        nodes = json.load(urllib.request.urlopen(req, timeout=30))['data']['hub']['tournaments']['nodes']
        evs = []
        for n in nodes:
            if n.get('isOnline') or not n.get('lat') or not n.get('startAt'):
                continue
            t = datetime.datetime.fromtimestamp(n['startAt'], NY)
            street = (n.get('venueAddress') or '').split(',')[0]
            place = (n.get('venueName') or 'NYC Next Level', street, n.get('city') or '', float(n['lat']), float(n['lng']))
            evs.append(event(place, n.get('name'), t.date().isoformat(), t.strftime('%H:%M'),
                             'https://www.start.gg/' + (n.get('slug') or ''), 'NYC Next Level', 'games'))
        return {'NYC Next Level': evs}
    except Exception as ex:
        return {'NYC Next Level': ex}


def dice(d0, d1):
    """Houses that sell through DICE. The feed is the promoter's whole calendar, soonest first, and includes
    nights it puts on in other rooms; only those at the house itself are kept, since the others reach the list
    through their own venues."""
    out = {}
    for key, name, api_key, promoters in DICE:
        place = PLACES[key]
        try:
            evs, total = [], 0
            for page in range(1, 5):
                q = urllib.parse.urlencode([('page[size]', 50), ('page[number]', page), ('types', 'linkout,event')] +
                                           [('filter[promoters][]', p) for p in promoters])
                data = json.loads(get('https://partners-endpoint.dice.fm/api/v2/events?' + q, {'x-api-key': api_key})).get('data') or []
                total += len(data)
                last = ''
                for e in data:
                    if not e.get('date'):
                        continue
                    t = datetime.datetime.fromisoformat(e['date'].replace('Z', '+00:00')).astimezone(NY)
                    last = t.date().isoformat()
                    loc = e.get('location') or {}
                    if not (d0 <= last <= d1) or e.get('status') == 'cancelled' or loc.get('lat') is None \
                            or routes.km(float(loc['lat']), float(loc['lng']), place[3], place[4]) > 0.15:
                        continue
                    # a bill is named "headliner, support, support"; anything else is a night with its own name
                    parts = [p.strip() for p in (e.get('name') or '').split(', ')]
                    artists = {(a or '').lower() for a in e.get('artists') or []}
                    title, acts = (parts[0], parts[1:]) if len(parts) > 1 and re.sub(r'\s*\([^)]*\)$', '', parts[0]).lower() in artists else (e.get('name'), [])
                    tags = ' '.join(e.get('type_tags') or [])
                    evs.append(event(place, title, last, t.strftime('%H:%M'), e.get('url') or e.get('external_url'), name,
                                     next((k for w, k in DICE_KINDS if w in tags), 'other'), acts,
                                     'Sold out.' if e.get('sold_out') else None))
                if len(data) < 50 or last > d1:
                    break
            out[name] = Found(evs, total)
        except Exception as ex:
            out[name] = ex
    return out


def _days(d0, d1):
    a, b = datetime.date.fromisoformat(d0), datetime.date.fromisoformat(d1)
    return [(a + datetime.timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def screenslate(d0, d1):
    """Repertory and arthouse screenings from Screen Slate's daily listings, kept to the cinemas in CINEMAS."""
    try:
        evs, total = [], 0
        for day in _days(d0, d1):
            slots = json.loads(get(f"https://www.screenslate.com/api/screenings/date?_format=json&date={day.replace('-', '')}&field_city_target_id=10969"))
            when = {x['nid']: x for x in slots}
            ids = list(when)
            total += len(ids)
            for i in range(0, len(ids), 40):
                got = json.loads(get('https://www.screenslate.com/api/screenings/id/' + '+'.join(ids[i:i + 40]) + '?_format=json'))
                for it in (got.values() if isinstance(got, dict) else got):
                    place = CINEMAS.get(clean(it.get('venue_title')))
                    slot = when.get(it.get('nid'))
                    if not place or not slot:
                        continue
                    t = slot.get('field_timestamp') or ''
                    title = clean(it.get('field_display_title')) or clean(it.get('media_title_labels')) or \
                        re.sub(r'\s+at\s+\S.*$', '', clean(it.get('title')))
                    info = ' · '.join(x for x in (clean(y) for y in re.findall(r'<span>(.*?)</span>', it.get('media_title_info') or '', re.S)) if x)
                    note = ' · '.join(x for x in (info, clean(it.get('field_series')), clean(slot.get('field_note'))) if x)
                    url = it.get('field_url') if str(it.get('field_url') or '').startswith('http') else 'https://www.screenslate.com/'
                    evs.append(event(place, title, t[:10] or day, t[11:16], url, 'Screen Slate', 'film', note=note))
        return {'Screen Slate': Found(evs, total)}
    except Exception as ex:
        return {'Screen Slate': ex}


def regal_astoria(d0, d1):
    """The Regal at Kaufman Astoria Studios. Regal's own site refuses automated requests, so this reads the
    same showtimes from Fandango's theater page data."""
    try:
        evs = []
        for day in _days(d0, d1):
            d = json.loads(get(f'https://www.fandango.com/napi/theaterMovieShowtimes/AAPOT?startDate={day}&isdesktop=true',
                               {'Referer': 'https://www.fandango.com/regal-ua-kaufman-astoria-aapot/theater-page'}))['viewModel']
            for m in d.get('movies') or []:
                title = re.sub(r'\s*\((?:19|20)\d\d\)\s*$', '', m.get('title') or '')
                url = 'https://www.fandango.com' + m['mopURI'] if (m.get('mopURI') or '').startswith('/') else 'https://www.fandango.com/regal-ua-kaufman-astoria-aapot/theater-page'
                for v in m.get('variants') or []:
                    fmt = clean(v.get('format') or v.get('formatName') or '')
                    for g in v.get('amenityGroups') or []:
                        for st in g.get('showtimes') or []:
                            td = st.get('ticketingDate') or ''
                            if len(td) >= 16 and td[:10] == day:
                                evs.append(event(REGAL_ASTORIA, title, td[:10], td[11:16], url, 'Fandango', 'film',
                                                 note=fmt if fmt and fmt.lower() != 'standard' else None))
        return {'Regal Astoria (Fandango)': evs}
    except Exception as ex:
        return {'Regal Astoria (Fandango)': ex}


MONTHS = {m: i + 1 for i, m in enumerate(['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august',
                                          'september', 'october', 'november', 'december'])}


def vanguard(d0, d1):
    """Week-long runs from the club's front page. Its FAQ gives the set times: 8:00 and 10:00 every night."""
    place = PLACES['vanguard']
    try:
        h = get('https://villagevanguard.com/')
        today = datetime.date.fromisoformat(d0)

        def day(month, n):
            for y in (today.year, today.year + 1, today.year - 1):
                try:
                    d = datetime.date(y, MONTHS[month.lower()], int(n))
                except ValueError:
                    continue
                if -200 < (d - today).days < 200:
                    return d
        evs, seen = [], set()
        for block in re.split(r'<div class="event-listing', h)[1:]:
            text = clean(block.split('>', 1)[-1])
            m = re.search(r'^(.*?)\s+([A-Z][a-z]+)\s+(\d{1,2})\s*[\u2010-\u2015-]\s*([A-Z][a-z]+)?\s*(\d{1,2})\b', text)
            if m and m.group(2).lower() in MONTHS and (m.group(4) or m.group(2)).lower() in MONTHS:
                title = m.group(1).strip()
                a, b = day(m.group(2), m.group(3)), day(m.group(4) or m.group(2), m.group(5))
                dates = [a + datetime.timedelta(days=i) for i in range((b - a).days + 1)] if a and b and a <= b else []
                dates = [d for d in dates if d.weekday() != 0]          # Mondays belong to the house orchestra
            elif re.match(r'VANGUARD JAZZ ORCHESTRA\s+Every Monday', text):
                title = 'Vanguard Jazz Orchestra'
                span = (datetime.date.fromisoformat(d1) - today).days
                dates = [d for d in (today + datetime.timedelta(days=i) for i in range(span + 1)) if d.weekday() == 0]
            else:
                continue
            if title.isupper():
                title = title.title()
            for d in dates:
                for t in ('20:00', '22:00'):
                    if (d, t) not in seen:
                        seen.add((d, t))
                        evs.append(event(place, title, d.isoformat(), t, 'https://villagevanguard.com/', 'Village Vanguard', 'music'))
        return {'Village Vanguard': evs}
    except Exception as ex:
        return {'Village Vanguard': ex}


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
                # a house hides its private nights (galas, patron nights) from its own site, and tests its site with fake events
                if not e or i.get('cancelled') or i.get('attribute_VirtualEvent') or e.get('attribute_HideOnWeb') \
                        or re.search(r'\[staging\]|\bwebsite test', e.get('name') or '', re.I):
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
    with ThreadPoolExecutor(10) as ex:
        for r in ex.map(lambda f: f(d0, d1), (ovationtix, spektrix, bam, todaytix, wonderville, startgg, vanguard, dice, screenslate, regal_astoria)):
            results.update(r)
    events, report = {d: [] for d in days}, {d: [] for d in days}
    for name, got in results.items():
        for d in days:
            if isinstance(got, Exception):
                report[d].append(dict(source=name, ok=False, error=str(got)[:120]))
            else:
                mine = [e for e in got if e['date'] == d and e['title']]
                events[d] += mine
                report[d].append(dict(source=name, ok=True, found=getattr(got, 'total', len(got)), on_date=len(mine)))
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
