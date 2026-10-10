#!/usr/bin/env python3
"""The Skint (theskint.com) is a hand-written daily list of free and cheap things to do. Its entries are prose,
so they are read by a model rather than parsed.

    python3 skint.py            print the current posts as plain text, links kept as [text](url)

Whatever runs the daily pull reads that text, writes the entries for the days it wants as JSON, and passes the
file to cloud.py with --skint. cloud.py checks each entry, looks up its address and labels it as coming from
the Skint, with a link back to the post.
"""
import html, re, sys

import sources

URL = 'https://theskint.com/'


def text():
    h = sources.get(URL)
    h = re.sub(r'<(script|style|noscript|svg|nav|footer|form)\b.*?</\1>', ' ', h, flags=re.S | re.I)
    h = re.sub(r'<a\b[^>]*href="([^"#][^"]*)"[^>]*>(.*?)</a>', lambda m: f'[{re.sub(r"<[^>]+>", "", m.group(2)).strip()}]({m.group(1)})', h, flags=re.S | re.I)
    h = re.sub(r'<(br|/p|/div|/h[1-6]|/li)\b[^>]*>', '\n', h, flags=re.I)
    t = html.unescape(re.sub(r'<[^>]+>', ' ', h))
    lines = [re.sub(r'[ \t\xa0]+', ' ', l).strip() for l in t.split('\n')]
    return '\n'.join(l for l in lines if l)


if __name__ == '__main__':
    sys.stdout.write(text() + '\n')
