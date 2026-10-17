#!/usr/bin/env python3
"""Non-concert sources: theater, dance, opera, film and the fringe houses. Stdlib only.

    python3 sources.py 2026-10-10            print what each source gives for a day
    python3 sources.py --build-venues        refresh tt_venues.json (addresses of TodayTix venues)

Most of these read a ticketing system rather than a venue's web page, because one reader then covers every
house that sells through it:

  OvationTix   La MaMa, Performance Space New York, Abrons, The Bushwick Starr, The Brick, Danspace Project,
               Roulette, Dixon Place, Nuyorican Poets Cafe, and the Off-Broadway rental houses SoHo Playhouse,
               Theater for the New City, The Players Theatre, The Flea, Target Margin, The Wild Project, WP Theater,
               York Theatre, Baryshnikov Arts, New Ohio, Theater Lab, Rattlestick
  Spektrix     St. Ann's Warehouse, New York Theatre Workshop, PAC NYC, Soho Rep, 59E59, Irish Rep, Vineyard,
               Atlantic, MCC, Signature, The New Group, Classic Stage, Theatre for a New Audience, The Tank,
               Symphony Space. (Primary Stages plays 59E59 and comes in with it.)
               Always through system.spektrix.com: the cloud pull's network refuses houses' own tickets.* names.
  Tessitura    Playwrights Horizons, Second Stage, Irish Arts Center, New Victory, the Joyce, through the calendar API behind
               each house's TNEW ticket site (its own host name, so each needs a place on the cloud allowlist)
  TodayTix     Broadway and Off-Broadway plays and musicals, the Met, City Center and others (about 300 shows).
               Only the shows whose producers list there: a rental house runs many more, hence the houses above.
  own sites    Roundabout (its WordPress feed), MTC and Lincoln Center Theater (their calendar pages), Ars Nova
               (Playtime), Cherry Lane (vivenu), Chain Theatre (Squarespace), HERE (CueBox), Ensemble Studio Theatre and
               New York Live Arts (Salesforce PatronManager), Japan Society (Ticketure), Pioneer Works (Sanity)
  comedy.py    twenty-two comedy clubs and the comedy nights at mixed rooms (readers in comedy_feeds.py)
  talks.py     bookstore readings, Cooper Union talks, the Poetry Project, and gallery openings from
               Artforum's artguide and Artsy (readers in talks_feeds.py), each placed by its own address
  BAM          its own calendar feed, which includes the cinemas
  DICE         Saint Vitus Bar, from the listing feed behind the show list on its own site
  and three single houses: Wonderville, the Village Vanguard, NYC Next Level (fighting-game weeklies)
  cinemas.py   repertory and arthouse cinemas, each from its own site (Screen Slate, which had them all, now blocks bots)
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
    'ph':       ('Playwrights Horizons', '416 W. 42nd St.', 'Manhattan', 40.75863, -73.99361),
    '2st':      ('Second Stage', '305 W. 43rd St.', 'Manhattan', 40.75808, -73.98950),          # the Tony Kiser Theater
    'hayes':    ('Hayes Theater', '240 W. 44th St.', 'Manhattan', 40.75785, -73.98784),         # Second Stage's Broadway house
    'iac':      ('Irish Arts Center', '726 11th Ave.', 'Manhattan', 40.76661, -73.99363),
    'newvic':   ('New Victory Theater', '209 W. 42nd St.', 'Manhattan', 40.75653, -73.98747),
    'joyce':    ('The Joyce', '175 Eighth Ave.', 'Manhattan', 40.74281, -74.00071),
    'tank':     ('The Tank', '312 W. 36th St.', 'Manhattan', 40.75361, -73.99318),
    'chain':    ('Chain Theatre', '312 W. 36th St., 4th fl.', 'Manhattan', 40.75361, -73.99318),
    'symphony': ('Symphony Space', '2537 Broadway', 'Manhattan', 40.79396, -73.97266),
    'theaterlab': ('Theater Lab', '357 W. 36th St., 3rd fl.', 'Manhattan', 40.75452, -73.99455),
    'rattlestick': ('Rattlestick Theater', '224 Waverly Pl.', 'Manhattan', 40.73615, -74.00202),
    'mtc':      ('Manhattan Theatre Club', '261 W. 47th St.', 'Manhattan', 40.76038, -73.98672),  # the Friedman
    'mtc1':     ('MTC at City Center', '131 W. 55th St.', 'Manhattan', 40.76393, -73.97946),
    'pels':     ('Laura Pels Theatre', '111 W. 46th St.', 'Manhattan', 40.75762, -73.98260),
    'haimes':   ('Todd Haimes Theatre', '227 W. 42nd St.', 'Manhattan', 40.75715, -73.98811),
    'studio54': ('Studio 54', '254 W. 54th St.', 'Manhattan', 40.76434, -73.98377),
    'lct':      ('Lincoln Center Theater', '150 W. 65th St.', 'Manhattan', 40.77367, -73.98480),
    'arsnova':  ('Ars Nova', '511 W. 54th St.', 'Manhattan', 40.76765, -73.99049),
    'cherry':   ('Cherry Lane Theatre', '38 Commerce St.', 'Manhattan', 40.73124, -74.00528),
    'here':     ('HERE', '145 Sixth Ave.', 'Manhattan', 40.72506, -74.00507),
    'est':      ('Ensemble Studio Theatre', '545 W. 52nd St.', 'Manhattan', 40.76700, -73.99277),
    'nyla':     ('New York Live Arts', '219 W. 19th St.', 'Manhattan', 40.74214, -73.99831),
    'japansoc': ('Japan Society', '333 E. 47th St.', 'Manhattan', 40.75255, -73.96824),
    'pioneer':  ('Pioneer Works', '159 Pioneer St.', 'Brooklyn', 40.67937, -74.01189),
    'bam':      ('BAM', '30 Lafayette Ave.', 'Brooklyn', 40.68650, -73.97780),
    'nuyorican': None,           # the cafe is dark for renovation and its nights move around; each one is placed by its ticket page
    'wonderville': ('Wonderville', '1186 Broadway', 'Brooklyn', 40.69189, -73.92808),
    'vanguard': ('Village Vanguard', '178 Seventh Ave. South', 'Manhattan', 40.73604, -74.00162),
    'vitus':    ('Saint Vitus Bar', '428 Troutman St.', 'Brooklyn', 40.70716, -73.92200),
}
# Cinemas read by cinemas.py, by name. A short list on purpose: the houses the city is known for, not every screen.
# BAM is left out here because its own feed above already covers it.
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
           ('wp', 34655, 'theater'), ('york', 34375, 'theater'), ('bac', 31295, 'other'), ('newohio', 34708, 'theater'),
           ('theaterlab', 28175, 'theater'), ('rattlestick', 34100, 'theater')]
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
            ('tfana', 'https://system.spektrix.com/tfana', 'https://www.tfana.org/'),
            ('tank', 'https://system.spektrix.com/thetanknyc', 'https://thetanknyc.org/'),
            ('symphony', 'https://system.spektrix.com/symphonyspace', 'https://www.symphonyspace.org/')]
# Tessitura houses, read through the calendar API behind their TNEW ticket sites: place key, ticket host, default
# kind, and (pattern, place key) rooms for a house with more than one stage, matched against the production's description
TNEW = [('ph', 'my.playwrightshorizons.org', 'theater', []),
        ('2st', 'cart.2st.com', 'theater', [(r'\bBroadway\b', 'hayes')]),
        ('iac', 'tickets.irishartscenter.org', 'other', []),
        ('newvic', 'tickets.newvictory.org', 'theater', []),
        ('joyce', 'shop.joyce.org', 'dance', [])]
# what a production is, from its title and description, for houses that sell more than plays. First match wins.
TNEW_KINDS = [(r'\bin conversation\b|\breading\b|\bpoetry', 'talk'), (r'choreograph|\bdance|ballet', 'dance'),
              (r'\bsessions?\b|\bfolk\b|\bconcert\b|\bband\b', 'music'), (r'\bcomed(y|ian)\b|\bstand-?up\b', 'comedy')]
# not a show: gallery exhibitions sold as timed entry, classes
TNEW_SKIP = r'\bexhibition\b|\binstallation\b|\bmaster ?class\b|\bworkshop\b|\bgift card|\bmembership\b'
# place key, source name, and the partner key and promoter names the house's own page hands to DICE's list widget
DICE = [('vitus', 'Saint Vitus', '1RsJ9u1HnFaj5F5hqFD7F9Idwsqi0o4z7QMQ2uGw',
         ['Saint Vitus LLC (dba Saint Vitus Bar)', 'SV Cathedral LLC'])]
DICE_KINDS = [('music', 'music'), ('theatre', 'theater'), ('film', 'film'), ('comedy', 'comedy'), ('talk', 'talk')]
TT_KINDS = {'Plays': 'theater', 'Musicals': 'theater', 'Opera': 'opera', 'Dance': 'dance', 'Concerts': 'music',
            'Comedy Shows': 'comedy', 'Cabaret': 'music', 'Films': 'film', 'Immersive Experiences': 'theater',
            'Circus and Magic': 'theater', 'Conversations': 'talk', 'Events': 'other'}
GENRE_WORDS = [('film', 'film'), ('cinema', 'film'), ('opera', 'opera'), ('dance', 'dance'), ('ballet', 'dance'),
               ('theat', 'theater'), ('music', 'music'), ('comedy', 'comedy'), ('improv', 'comedy'), ('talk', 'talk'), ('storytell', 'talk'), ('literary', 'talk')]


def get(url, headers=None, timeout=30, data=None):
    """GET a page, or POST `data` (a dict, sent as JSON) to it."""
    h = {'User-Agent': UA, 'Accept-Encoding': 'gzip', 'Accept': 'application/json, text/html;q=0.9, */*;q=0.8'}
    if data is not None:
        h['Content-Type'] = 'application/json'
        data = json.dumps(data).encode()
    h.update(headers or {})
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=timeout) as r:
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
                         label, rooms[pid][1], note=None if re.search(r'click here|tickets?\b|^\s*$', sub or '', re.I) else sub)
                   for pid, name, t, sub in rows if rooms[pid][0]]   # a subtitle is a credit line or a tagline, not a list of acts
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
                if not e or i.get('cancelled') or i.get('attribute_VirtualEvent') or e.get('attribute_VirtualEvent') \
                        or e.get('attribute_HideOnWeb') or e.get('attribute_SLExcludeFromViewEventsPage') \
                        or re.search(r'\[staging\]|\bwebsite test', e.get('name') or '', re.I):
                    continue
                t = i.get('start') or ''
                evs.append(event(place, e.get('name'), t[:10], t[11:16], e.get('webUrl') or site, place[0],
                                 kind_of(e.get('attribute_Genre1') or e.get('attribute_Genre'), 'theater')))
            out[place[0]] = evs
        except Exception as ex:
            out[place[0]] = ex
    return out


def tnew(d0, d1):
    out = {}
    end = (datetime.date.fromisoformat(d1) + datetime.timedelta(days=1)).isoformat()
    for key, host, default_kind, rooms in TNEW:
        place = PLACES[key]
        try:
            got = json.loads(get(f'https://{host}/api/products/productionseasons', data={
                'productionSeasonIdFilter': [], 'keywordIds': [], 'startDate': d0 + 'T00:00:00', 'endDate': end + 'T00:00:00'}))
            evs = []
            for p in got.get('productions') or []:
                title, desc = p.get('productionTitle') or '', clean(p.get('description'))
                if re.search(TNEW_SKIP, title + ' ' + desc, re.I):
                    continue
                room = PLACES[next((k for pat, k in rooms if re.search(pat, desc)), key)]
                kind = next((k for pat, k in TNEW_KINDS if re.search(pat, title + ' ' + desc, re.I)), default_kind) \
                    if default_kind not in ('theater', 'dance') else default_kind
                for perf in p.get('performances') or []:
                    t = perf.get('iso8601DateString') or ''   # local time, with its offset
                    if not perf.get('isPerformanceVisible', True) or not t[:10]:
                        continue
                    evs.append(event(room, perf.get('performanceTitle') or title, t[:10], t[11:16],
                                     perf.get('actionUrl') or p.get('productionSeasonActionUrl') or f'https://{host}/events',
                                     place[0], kind))
            out[place[0]] = evs
        except Exception as ex:
            out[place[0]] = ex
    return out


def local(t):
    """(date, 'HH:MM') in New York for an ISO time with an offset or a Z, or epoch milliseconds."""
    if isinstance(t, (int, float)):
        d = datetime.datetime.fromtimestamp(t / 1000, NY)
    else:
        d = datetime.datetime.fromisoformat(t.replace('Z', '+00:00')).astimezone(NY)
    return d.date().isoformat(), d.strftime('%H:%M')


def roundabout(d0, d1):
    rooms = {'Laura Pels Theatre': 'pels', 'Todd Haimes Theatre': 'haimes', 'Studio 54': 'studio54'}
    for p in json.loads(get('https://www.roundabouttheatre.org/wp-json/roundabout/v1/performances/'))['performances']:
        pr = p.get('production') or {}
        yield event(PLACES[rooms.get(pr.get('theatreTitle'), 'pels')], pr.get('title'), p['date'][:10], p['date'][11:16],
                    p.get('url') or pr.get('url'), 'Roundabout', 'theater')


def mtc(d0, d1):
    """MTC's own calendar page: one block per performance, its class naming the stage."""
    page = get('https://www.manhattantheatreclub.com/our-season/calendar/')
    for chunk in page.split('<span class="bg_event ')[1:]:
        m = re.search(r'</span>\s*([A-Z][a-z]+ \d{1,2}, \d{4})\s*</h4>', chunk)
        title = re.search(r'<p class="event">(.*?)</p>\s*<p class="hours">\s*(\d{1,2}:\d\d)\s*([ap]m)', chunk, re.S)
        if not m or not title:
            continue
        day = datetime.datetime.strptime(m.group(1), '%B %d, %Y').date().isoformat()
        hh, mm = map(int, title.group(2).split(':'))
        hh = hh % 12 + (12 if title.group(3) == 'pm' else 0)
        buy = re.search(r'class="buy_now" href="([^"]+)"', chunk) or re.search(r'class="learn_more" href="([^"]+)"', chunk)
        yield event(PLACES['mtc1' if chunk.startswith('stage') else 'mtc'], title.group(1), day, f'{hh:02d}:{mm:02d}',
                    buy.group(1) if buy else 'https://www.manhattantheatreclub.com/', 'Manhattan Theatre Club', 'theater')


def lct(d0, d1):
    """Lincoln Center Theater: each show's schedule page links every performance to Telecharge, the time in the link."""
    page = get('https://www.lct.org/shows/')
    slugs = sorted(set(re.findall(r'href="(?:https://www\.lct\.org)?/shows/([a-z][a-z0-9-]+)/"', page))
                   - {'shows-archive', 'the-reading-series', 'people'})
    for slug in slugs:
        try:
            sched = get(f'https://www.lct.org/shows/{slug}/schedule/')
        except Exception:
            continue          # a show without a schedule page yet
        title = clean((re.search(r'<title>(.*?)</title>', sched, re.S) or [None, slug])[1]).split(' - Schedule')[0]
        if title.isupper():
            title = re.sub(r"\b(And|Of|The|A|An|In|With|For|To)\b", lambda m: m.group(1).lower(), title.title()).replace("'S", "'s")
            title = title[:1].upper() + title[1:]
        for url, mo, dd, yy, hh, mm, ap in set(re.findall(
                r'href="(https://www\.telecharge\.com/[^"]*PerformanceDateTime=(\d{1,2})/(\d{1,2})/(\d{4})%20(\d{1,2}):(\d\d)([AP]M)[^"]*)"', sched)):
            h = int(hh) % 12 + (12 if ap == 'PM' else 0)
            yield event(PLACES['lct'], title, f'{yy}-{int(mo):02d}-{int(dd):02d}', f'{h:02d}:{mm}', html.unescape(url),
                        'Lincoln Center Theater', 'theater')


def arsnova(d0, d1):
    for p in json.loads(get('https://api.arsnovanyc.playtime.world/api/v21/playtime/event/performances_anon?status=scheduled')):
        e = p.get('event') or {}
        day, t = local(p['start_date'])
        title = (e.get('qed_model') or {}).get('title')
        yield event(PLACES['arsnova'], title, day, t, f"https://arsnovanyc.playtime.world/event/{e.get('hashcode')}", 'Ars Nova',
                    'comedy' if re.search(r'comedy|stand-?up', title or '', re.I) else 'theater')


def cherrylane(d0, d1):
    page = get('https://shows.cherrylanetheatre.org/')
    data = json.loads(re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S).group(1))
    shop = data['props']['pageProps'].get('sellerPage') or {}
    if shop.get('events') is None:
        raise RuntimeError('vivenu sent the page without its events (an outage on their side, as on 2026-10-16)')
    for e in shop['events']:
        day, t = local(e['start'])
        yield event(PLACES['cherry'], e.get('name'), day, t, f"https://shows.cherrylanetheatre.org/event/{e.get('url')}",
                    'Cherry Lane', 'film' if re.search(r'screening|\bfilm\b', e.get('name') or '', re.I) else 'theater')


def chain(d0, d1):
    url, stop = 'https://www.chaintheatre.org/whats-on?format=json', d1
    for _ in range(6):
        got = json.loads(get(url))
        for e in got.get('upcoming') or []:
            day, t = local(e['startDate'])
            title = re.sub(r'^\s*RENTAL:\s*|\s*\((?:\d\w+|ground) floor\)\s*$', '', clean(e.get('title')), flags=re.I)
            yield event(PLACES['chain'], title, day, t, 'https://www.chaintheatre.org' + (e.get('fullUrl') or '/whats-on'), 'Chain Theatre',
                        'film' if re.search(r'\bfilm\b|screening', title, re.I) else 'theater')
            if day > stop:
                return
        nxt = (got.get('pagination') or {}).get('nextPageUrl')
        if not nxt:
            return
        url = 'https://www.chaintheatre.org' + nxt + '&format=json'


def here(d0, d1):
    """HERE sells through CueBox. The key is the public one CueBox's own ticket page sends."""
    got = json.loads(get('https://api.getcuebox.com/connect/cuebox.services.consumer.v1.CueboxConsumerService/ListShows',
                         data={'filter': 'LIST_SHOWS_FILTER_UPCOMING'},
                         headers={'Connect-Protocol-Version': '1', 'Cuebox-Org-Id': 'CCTQ0T6B',
                                  'Cuebox-Consumer-Api-Key': '1j0YyLEgz_Jho30m4-tn'}))
    for show in got.get('shows') or []:
        for r in show.get('showtimeTimeRanges') or []:
            day, t = local(r['start'])
            yield event(PLACES['here'], show.get('name'), day, t, f"https://here.app.getcuebox.com/o/CCTQ0T6B/shows/{show['id']}",
                        'HERE', 'theater', note=show.get('subtitle'))


def patronmanager(key, host, default_kind):
    """A house selling through Salesforce PatronManager: its public ticket page carries the keys for the remoting call
    that lists every event and performance."""
    import http.cookiejar
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    base = f'https://{host}/ticket/'
    page = op.open(urllib.request.Request(base, headers={'User-Agent': UA}), timeout=30).read().decode('utf-8', 'replace')
    cfg = json.loads(re.search(r'RemotingProviderImpl\((\{.*?\})\)\);', page, re.S).group(1))
    action, m = next((a, m) for a, v in cfg['actions'].items() for m in v['ms'] if m['name'] == 'fetchEvents')
    body = {'action': action, 'method': 'fetchEvents', 'data': [base, '', '', None][:m['len']], 'type': 'rpc', 'tid': 2,
            'ctx': {'csrf': m['csrf'], 'vid': cfg['vf']['vid'], 'ns': m['ns'], 'ver': int(m['ver']), 'authorization': m['authorization']}}
    req = urllib.request.Request(f'https://{host}/ticket/apexremote', data=json.dumps(body).encode(), headers={
        'User-Agent': UA, 'Content-Type': 'application/json', 'X-User-Agent': 'Visualforce-Remoting',
        'X-Requested-With': 'XMLHttpRequest', 'Referer': base, 'Origin': f'https://{host}'})
    got = json.loads(op.open(req, timeout=30).read())
    for e in got[0].get('result') or []:
        name = e.get('name') or ''
        if re.search(TNEW_SKIP + r'|\bmemberfest\b|\bdonat', name, re.I):
            continue
        for i in e.get('instances') or []:
            when = (i.get('formattedDates') or {}).get('ISO8601')
            if when is None or i.get('nonTimed'):
                continue
            day, t = local(when)
            yield event(PLACES[key], name, day, t, i.get('purchaseUrl') or e.get('purchaseUrl'), PLACES[key][0],
                        kind_of(e.get('category'), default_kind))


def japansociety(d0, d1):
    """Japan Society's Ticketure box office, kept to its performing-arts programs (it also sells classes and exhibitions)."""
    a = datetime.datetime.combine(datetime.date.fromisoformat(d0), datetime.time(), NY).astimezone(datetime.timezone.utc)
    b = a + datetime.timedelta(days=(datetime.date.fromisoformat(d1) - datetime.date.fromisoformat(d0)).days + 1)
    got = json.loads(get('https://boxoffice.japansociety.org/api/events/available?_embed=venue,event_session'
                         f"&event_session.start_datetime._gte={a:%Y-%m-%dT%H:%M:%SZ}&event_session.start_datetime._lt={b:%Y-%m-%dT%H:%M:%SZ}"))
    shows = {t['id']: t for t in got['event_template']['_data'] if t.get('category') in ('Performing Arts', 'Film')}
    for sn in got['event_session']['_data']:
        t = shows.get(sn['event_template_id'])
        if t:
            day, hm = local(sn['start_datetime'])
            yield event(PLACES['japansoc'], t.get('name'), day, hm, f"https://boxoffice.japansociety.org/events/{t['id']}",
                        'Japan Society', 'film' if t.get('category') == 'Film' else 'theater')


def pioneerworks(d0, d1):
    """Pioneer Works' programs, from the Sanity store behind its site. Open-gallery days are left out."""
    q = ('*[_type=="program" && calendar.startDate<="%s" && coalesce(calendar.endDate, calendar.startDate)>="%s"]'
         '{title, "slug": slug.current, calendar}' % (d1, d0))
    for p in json.loads(get('https://vgvol637.apicdn.sanity.io/v2021-10-21/data/query/production?query=' + urllib.parse.quote(q)))['result']:
        c = p.get('calendar') or {}
        if c.get('range') == 'gallery' or not c.get('startDate'):
            continue
        first, last = datetime.date.fromisoformat(c['startDate']), datetime.date.fromisoformat(c.get('endDate') or c['startDate'])
        title = p.get('title') or ''
        kind = 'talk' if re.search(r'\btalk\b|conversation|lecture|reading|book', title, re.I) else kind_of(title, 'music')
        for n in range(min((last - first).days, 14) + 1):
            yield event(PLACES['pioneer'], title, (first + datetime.timedelta(days=n)).isoformat(), c.get('startTime'),
                        f"https://pioneerworks.org/programs/{p.get('slug')}", 'Pioneer Works', kind)


OWN_SITES = [('Roundabout', roundabout), ('Manhattan Theatre Club', mtc), ('Lincoln Center Theater', lct), ('Ars Nova', arsnova),
             ('Cherry Lane', cherrylane), ('Chain Theatre', chain), ('HERE', here),
             ('Ensemble Studio Theatre', lambda a, b: patronmanager('est', 'ensemblestudiotheatre.my.salesforce-sites.com', 'theater')),
             ('New York Live Arts', lambda a, b: patronmanager('nyla', 'newyorklivearts.my.salesforce-sites.com', 'dance')),
             ('Japan Society', japansociety), ('Pioneer Works', pioneerworks)]


def own_sites(d0, d1):
    """Single houses read from their own sites, each a generator of events; kept to the dates asked, once each."""
    def one(f):
        try:
            seen, evs = set(), []
            for e in f(d0, d1):
                k = (e['title'].lower(), e['date'], e['time'])
                if d0 <= e['date'] <= d1 and e['title'] and k not in seen:
                    seen.add(k)
                    evs.append(e)
            return evs
        except Exception as ex:
            return ex
    with ThreadPoolExecutor(4) as ex:
        return dict(zip((n for n, _ in OWN_SITES), ex.map(one, (f for _, f in OWN_SITES))))


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
    import cinemas, comedy, talks       # here, not at the top: they read this module's helpers
    results = {}
    with ThreadPoolExecutor(10) as ex:
        for r in ex.map(lambda f: f(d0, d1), (ovationtix, spektrix, tnew, own_sites, bam, todaytix, wonderville, startgg, vanguard, dice, cinemas.screenings, comedy.shows, talks.items, regal_astoria)):
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
