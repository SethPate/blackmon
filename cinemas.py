"""Repertory and arthouse cinemas, each read from its own site. Stdlib only.

Screen Slate used to give all of these in one feed; since October 2026 it sits behind a bot check, so each house is
read directly. Kept to the houses the city is known for, not every screen: first-run multiplexes (Alamo, the
Angelika group) would bury the rest at sixty-odd shows a day each. MoMA's film calendar and DCTV's Firehouse are
behind bot checks too, and the Paris only answers to a login lifted from its own site's code, so those are left out.

    python3 cinemas.py 2026-10-17          print what each cinema gives for a day
"""
import datetime, html, json, re, sys, urllib.error

import sources
from sources import NY, clean, event, get

CINEMAS = dict(sources.CINEMAS, **{
    'Roxy Cinema': ('Roxy Cinema', '2 Sixth Ave.', 'Manhattan', 40.71927, -74.00483),
    'Quad Cinema': ('Quad Cinema', '34 W. 13th St.', 'Manhattan', 40.73596, -73.99596),
    'Syndicated': ('Syndicated', '40 Bogart St.', 'Brooklyn', 40.70498, -73.93308),
    'Film Noir Cinema': ('Film Noir Cinema', '122 Meserole Ave.', 'Brooklyn', 40.72731, -73.95160),
    'Light Industry': ('Light Industry', '155 Freeman St.', 'Brooklyn', 40.73453, -73.95562),
})
MONTHS = {m: i for i, m in enumerate(['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august',
                                      'september', 'october', 'november', 'december'], 1)}


def near(ref, month, day):
    """The date with this month and day nearest to ref: listings that give no year."""
    out = []
    for y in (ref.year - 1, ref.year, ref.year + 1):
        try:
            out.append(datetime.date(y, month, day))
        except ValueError:
            pass
    return min(out, key=lambda d: abs((d - ref).days))


def hm(t):
    """'7:30 PM', '9pm', '4.50pm' -> '19:30'."""
    m = re.match(r'\s*(\d{1,2})(?:[:.](\d\d))?\s*([ap])\.?m', t, re.I)
    h = int(m.group(1)) % 12 + (12 if m.group(3).lower() == 'p' else 0)
    return f'{h:02d}:{int(m.group(2) or 0):02d}'


def show(name, title, day, time, url, note=None):
    return event(CINEMAS[name], title, day.isoformat() if isinstance(day, datetime.date) else day, time, url, name, 'film',
                 note=note)


def local(dt):
    d = dt.astimezone(NY) if dt.tzinfo else dt
    return d.date().isoformat(), d.strftime('%H:%M')


def film_forum(d0, d1):
    page, ref = get('https://filmforum.org/now_playing'), datetime.date.fromisoformat(d0)
    today = datetime.datetime.now(NY).date()
    for tab, dom, body in re.findall(r'<div id="tabs-(\d)">\s*<!--\s*(\d+)\s*-->(.*?)</div>', page, re.S):
        day = today + datetime.timedelta(days=int(tab))                   # tab 0 is today
        if day.day != int(dom):
            day = near(ref, ref.month if int(dom) >= ref.day else ref.month % 12 + 1, int(dom))
        for p in re.findall(r'<p>(.*?)</p>', body, re.S):
            t = re.search(r'<strong><a href="([^"]+)">(.*?)</a></strong>', p, re.S)
            if not t:
                continue
            series = re.match(r'\s*(?:<span[^>]*>.*?</span>)?\s*<a href="[^"]*series[^"]*">(.*?)</a>', p, re.S)
            for hh, mm in re.findall(r'<span>(\d{1,2}):(\d\d)</span>', p):
                h = int(hh)
                h = h if h in (10, 11, 12) else h + 12                     # the site prints no AM/PM: 10 to 12 are daytime
                yield show('Film Forum', t.group(2), day, f'{h:02d}:{mm}', t.group(1), clean(series.group(1)) if series else None)


def metrograph(d0, d1):
    page = get('https://metrograph.com/nyc/')
    for day, body in re.findall(r'id="calendar-list-day-(\d{4}-\d\d-\d\d)">(.*?)(?=<div class="calendar-list-day|$)', page, re.S):
        for item in body.split('<div class="item film-thumbnail')[1:]:
            t = re.search(r'<a href="([^"]+)" class="title">(.*?)</a>', item, re.S)
            meta = re.search(r'class="film-metadata">(.*?)</div>', item, re.S)
            st = re.search(r'class="showtimes">(.*?)</div>', item, re.S)
            if not t:
                continue
            for cls, a in re.findall(r'<a([^>]*)>\s*([0-9:]+\s*[ap]m)\s*</a>', st.group(1) if st else '', re.I):
                note = ' · '.join(x for x in (clean(meta.group(1)) if meta else '', 'sold out' if 'sold_out' in cls else '') if x)
                yield show('Metrograph', t.group(2), day, hm(a), t.group(1), note)


def ifc(d0, d1):
    page, ref = get('https://www.ifccenter.com/'), datetime.date.fromisoformat(d0)
    for hdr, body in re.findall(r'<div class="daily-schedule [a-z]{3}[^"]*">\s*<h3>(.*?)</h3>(.*?)(?=<div class="daily-schedule|$)', page, re.S):
        m = re.search(r'([A-Z][a-z]{2}) (\d+)', hdr)
        if not m:
            continue                                                       # the coming-soon block
        day = near(ref, datetime.datetime.strptime(m.group(1), '%b').month, int(m.group(2)))
        for li in body.split('<div class="details">')[1:]:
            t = re.search(r'<h3><a href="([^"]+)">(.*?)</a></h3>', li, re.S)
            for tm in re.findall(r'<a href="[^"]+">\s*(\d{1,2}:\d\d [AP]M)\s*</a>', li) if t else ():
                yield show('IFC Center', t.group(2), day, hm(tm), t.group(1))


def flc(d0, d1):
    """Film at Lincoln Center's own API; it lists only screenings still on sale."""
    for f in json.loads(get('https://api.filmlinc.org/showtimes'))['films']:
        for s in f['showtimes']:
            day, t = local(datetime.datetime.fromisoformat(s['dateTimeET']))
            yield show('Film at Lincoln Center', f['title'], day, t, f"https://www.filmlinc.org/films/{f['slug']}/", s.get('venue'))


def anthology(d0, d1):
    a, b = datetime.date.fromisoformat(d0), datetime.date.fromisoformat(d1)
    for y, mth in sorted({(a.year, a.month), (b.year, b.month)}):
        url = f'https://www.anthologyfilmarchives.org/film_screenings/calendar?view=list&month={mth}&year={y}'
        page = get(url)
        for dom, body in re.findall(r'<a name="day-(\d\d)"></a>(.*?)(?=<a name="day-|<div id="footer|$)', page, re.S):
            for sh in body.split('<div class="film-showing')[1:]:
                m = re.search(r'<a name="showing-(\d+)">\s*([0-9:]+ [AP]M)</a>', sh)
                t = re.search(r'<span class="film-title">(.*?)</span>', sh, re.S)
                if m and t:
                    series = re.search(r'series-note">.*?<a[^>]*>(.*?)</a>', sh, re.S)
                    yield show('Anthology Film Archives', t.group(1), datetime.date(y, mth, int(dom)), hm(m.group(2)),
                               f'{url}#showing-{m.group(1)}', clean(series.group(1)) if series else None)


def momi(d0, d1):
    """Only the site's RSS feed gets past its bot check. Upcoming events in start order, ten a page; a screening is an
    item with a director credit or a ticket line, which leaves out the exhibitions, tours and classes."""
    for n in range(1, 15):
        try:
            page = get('https://movingimage.org/feed/?post_type=tribe_events' + (f'&paged={n}' if n > 1 else ''))
        except urllib.error.HTTPError as ex:
            if ex.code == 404:
                return
            raise
        items, last = re.findall(r'<item>(.*?)</item>', page, re.S), None
        for it in items:
            start = datetime.datetime.strptime(re.search(r'<pubDate>(.*?)</pubDate>', it).group(1), '%a, %d %b %Y %H:%M:%S %z')
            day, t = local(start)
            last = day
            body = (re.search(r'<content:encoded><!\[CDATA\[(.*?)\]\]>', it, re.S) or [None, ''])[1]
            credit = re.search(r'Dir\.\s*([^<]{3,200}?(?:mins?|DCP|35mm|70mm|16mm)\.?)', clean(body))
            if d0 <= day <= d1 and (credit or 'Order tickets' in body or 'Tickets:' in body):
                yield show('Museum of the Moving Image', html.unescape(re.search(r'<title>(.*?)</title>', it).group(1)), day, t,
                           re.search(r'<link>(.*?)</link>', it).group(1), credit.group(0) if credit else None)
        if not items or (last and last > d1):
            return


def nitehawk(site, name):
    def read(d0, d1):
        got = json.loads(get(f'https://nitehawkcinema.com/{site}/wp-json/nj/v1/showtime/listings'))
        movies = {m['movie_id']: m for m in got['movies']}
        for s in got['showtimes']:
            start = datetime.datetime.strptime(s['datetime'], '%Y%m%d%H%M%S')
            if start.hour < 5:
                start += datetime.timedelta(days=1)                        # a midnight show is listed under the evening before
            m = movies.get(s['movie_id'], {})
            note = ' · '.join(x for x in (m.get('release_year') or '', s.get('qualifier') or '') if str(x).strip())
            yield show(name, m.get('movie_name') or '', start.date(), start.strftime('%H:%M'), s.get('purchase_url'), note or None)
    return read


def spectacle(d0, d1):
    """Spectacle posts one page per series, its dates written out in the text ('MONDAY, OCTOBER 19 – 7:30 PM')."""
    ref = datetime.date.fromisoformat(d0)
    rx = re.compile(r'\b(?:MON|TUES?|WED(?:NES)?|THU(?:RS)?|FRI|SAT(?:UR)?|SUN)[A-Z]*,?\s+([A-Z]+)\.?\s+(\d{1,2})'
                    r'(?:ST|ND|RD|TH)?\s*(?:[–—@-])\s*(\d{1,2}(?::\d\d)?\s*[AP]\.?M)', re.I)
    for p in json.loads(get('https://www.spectacletheater.com/wp-json/wp/v2/posts?per_page=40&_fields=link,title,content')):
        body = html.unescape(re.sub(r'<[^>]+>', ' ', p['content']['rendered']))
        credit = re.search(r'Dir\. [^.]+, \d{4}\.[^\n]{0,80}?min\.', body)
        for mon, dom, tm in set(rx.findall(body)):
            if mon.lower() in MONTHS:
                yield show('Spectacle', p['title']['rendered'], near(ref, MONTHS[mon.lower()], int(dom)), hm(tm), p['link'],
                           credit.group(0) if credit else None)


def roxy(d0, d1):
    page = get('https://www.roxycinemanewyork.com/now-showing')
    for card in page.split("class='detailed-screening__card'")[1:]:
        when = re.search(r"data-datetime='([^']+)'", card)
        title = re.search(r"class='detailed-screening__title'>(.*?)</h3>", card, re.S)
        if not (when and title):
            continue
        day, t = local(datetime.datetime.strptime(when.group(1), '%Y-%m-%dT%H:%M:%S.%f%z'))
        info = re.search(r"class='detailed-screening__info'>(.*?)</p>", card, re.S)
        link = re.search(r'href="(https://www\.roxycinemanewyork\.com/screenings/[^"]+)"', card)
        yield show('Roxy Cinema', title.group(1), day, t, link.group(1) if link else 'https://www.roxycinemanewyork.com/now-showing',
                   clean(info.group(1)) if info else None)


def quad(d0, d1):
    page, today = get('https://quadcinema.com/'), datetime.datetime.now(NY).date()
    for dom, body in re.findall(r'<div class="day-wrap date-(\d+)[^"]*">(.*?)(?=<div class="day-wrap|</section|<footer)', page, re.S):
        day = next((today + datetime.timedelta(days=i) for i in range(8) if (today + datetime.timedelta(days=i)).day == int(dom)), None)
        for item in body.split('grid-item">')[1:] if day else ():
            t = re.search(r'<h4><a href="([^"]+)">(.*?)</a></h4>', item, re.S)
            for tm in re.findall(r'<li class="time-[^"]*"><a[^>]*>([0-9.]+[ap]m)</a>', item) if t else ():
                yield show('Quad Cinema', t.group(2), day, hm(tm), t.group(1))


def syndicated(d0, d1):
    """Syndicated sells through Veezi, whose sessions page is plain HTML; the by-date half comes first."""
    url = 'https://ticketing.useast.veezi.com/sessions/?siteToken=dxdq5wzbef6bz2sjqt83ytzn1c'
    page, ref = get(url).split('id="sessionsByFilmConent"')[0], datetime.date.fromisoformat(d0)
    for block in page.split('<div class="date">')[1:]:
        for film in block.split('class="film ')[1:]:
            title = re.search(r'<h3 class="title">(.*?)</h3>', film, re.S)
            for dc in film.split('<div class="date-container">')[1:] if title else ():
                dm = re.search(r'<h4 class="date">\w+ (\d+), (\w+)</h4>', dc)
                if not dm or dm.group(2).lower() not in MONTHS:
                    continue
                day = near(ref, MONTHS[dm.group(2).lower()], int(dm.group(1)))
                for href, tm in re.findall(r'<a(?: href="([^"]*)")?[^>]*>\s*<time>([^<]+)</time>', dc):
                    yield show('Syndicated', title.group(1), day, hm(tm), html.unescape(href) if href else url,
                               None if href else 'sold out')


def filmnoir(d0, d1):
    for e in json.loads(get('https://www.filmnoircinema.com/program?format=json')).get('upcoming') or []:
        day, t = local(datetime.datetime.fromtimestamp(e['startDate'] / 1000, NY))
        yield show('Film Noir Cinema', e.get('title'), day, t, 'https://www.filmnoircinema.com' + (e.get('fullUrl') or '/program'))


def light_industry(d0, d1):
    """Light Industry's calendar gives the day; each event's own page gives the time."""
    page, ref = get('https://www.lightindustry.org/calendar/'), datetime.date.fromisoformat(d0)
    upcoming = page.split('Past Events')[0]
    for md, href, title in re.findall(r'<strong>([A-Z][a-z]+ \d+)</strong>:\s*<a href="([^"]+)"[^>]*>(.*?)</a>', upcoming, re.S):
        mo, dom = md.split()
        if mo.lower() not in MONTHS:
            continue
        day = near(ref, MONTHS[mo.lower()], int(dom))
        if not d0 <= day.isoformat() <= d1:
            continue
        m = re.search(r'\w+day, \w+ \d+, \d{4} at (\d{1,2}(?::\d\d)?\s*[ap]m)', clean(get(href)), re.I)
        yield show('Light Industry', title, day, hm(m.group(1)) if m else None, href)


READERS = [('Film Forum', film_forum), ('Metrograph', metrograph), ('IFC Center', ifc), ('Film at Lincoln Center', flc),
           ('Anthology Film Archives', anthology), ('Museum of the Moving Image', momi),
           ('Nitehawk Williamsburg', nitehawk('williamsburg', 'Nitehawk Cinema Williamsburg')),
           ('Nitehawk Prospect Park', nitehawk('prospectpark', 'Nitehawk Cinema Prospect Park')),
           ('Spectacle', spectacle), ('Roxy Cinema', roxy), ('Quad Cinema', quad), ('Syndicated', syndicated),
           ('Film Noir Cinema', filmnoir), ('Light Industry', light_industry)]


def screenings(d0, d1):
    """{cinema: [events] or the exception it raised}, kept to the dates asked and to one copy of each showing."""
    def one(f):
        try:
            seen, evs = set(), []
            for e in f(d0, d1):
                k = (e['title'].lower(), e['date'], e['time'])
                if e['title'] and d0 <= e['date'] <= d1 and k not in seen:
                    seen.add(k)
                    evs.append(e)
            return evs
        except Exception as ex:
            return ex
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(6) as ex:
        return dict(zip((n for n, _ in READERS), ex.map(one, (f for _, f in READERS))))


if __name__ == '__main__':
    d = sys.argv[1] if len(sys.argv) > 1 else datetime.datetime.now(NY).date().isoformat()
    for name, got in screenings(d, d).items():
        print(f'== {name}:', got if isinstance(got, Exception) else len(got))
        for e in ([] if isinstance(got, Exception) else sorted(got, key=lambda e: e['time'] or ''))[:4]:
            print('  ', e['time'], e['title'][:50], '|', (e['note'] or '')[:50], '|', e['url'][:60])
