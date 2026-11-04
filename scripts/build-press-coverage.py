#!/usr/bin/env python3
"""Build the BanVoyage press-coverage data file and render it into index.html.

Source rows are the Press Advantage pickup report. The page stays static:
every pickup is a real <a href> in index.html, not loaded by JavaScript.

Dedupe: exact URL. When the same URL is present as both http and https, keep
https. Rows with an empty host_name are labeled by their domain.

Featured outlets are a fixed set of recognizable newspaper, television, and
market names, ordered by host_page_rank (higher is stronger).
"""

from __future__ import annotations

import csv
import html
import json
import re
import sys
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
DATA = ROOT / "data" / "press-coverage.json"
DEFAULT_CSV = Path(
    "/home/ubuntu/.cursor/projects/workspace/uploads/press-pickups-2026-11-03_653b.csv"
)

RELEASE_TITLE = (
    "Brooke and Laurence Banville Launch BanVoyage Travel Site BanVoyage.com"
)
RELEASE_DATE = "2026-11-03"
RELEASE_DATE_DISPLAY = "November 3, 2026"
RELEASE_URL = (
    "https://pressadvantage.com/story/109280-brooke-and-laurence-banville-"
    "launch-banvoyage-travel-site-banvoyage-com"
)
MEDIA_URL = "https://pressadvantage.com/i_organization/banvoyage"
SITE_URL = "https://banvoyage.com/"
ARTICLE_ID = RELEASE_URL + "#NewsArticle"
LIST_ID = "https://laurence-lpblg.github.io/banvoyage-press/#FeaturedPress"
PAGE_MODIFIED = "2026-11-04"

# Recognizable newspaper, TV, and market outlets. URLs and ranks come from the
# report; this list only chooses which names to feature.
FEATURED_NAMES = [
    "USA TODAY",
    "Arizona Republic",
    "The Detroit News",
    "Cincinnati Enquirer",
    "Des Moines Register",
    "Telegram & Gazette",
    "Wicked Local",
    "Akron Beacon Journal",
    "Delaware Online",
    "Florida Today",
    "Green Bay Press-Gazette",
    "Providence Journal",
    "Citizen-Times",
    "Post-Crescent",
    "Savannah Morning News",
    "Wausau Daily Herald",
    "Reno Gazette Journal",
    "Tallahassee Democrat",
    "Treasure Coast Newspapers",
    "Visalia Times-Delta",
    "Palm Beach Daily News",
    "Peoria Journal Star",
    "South Bend Tribune",
    "Ventura County Star",
    "Norwich Bulletin",
    "Pittsburgh Post-Gazette",
    "San Diego Union-Tribune",
    "Star Tribune",
    "Buffalo News",
    "WRAL",
]


def decode_name(value: str) -> str:
    text = (value or "").strip()
    for _ in range(2):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded.strip()
    return re.sub(r"\s+", " ", text)


def domain_label(url: str) -> str:
    host = urlparse(url).netloc
    if host.lower().startswith("www."):
        host = host[4:]
    return host


def scheme_key(url: str) -> str:
    """Identity used to collapse an http/https pair. The rest of the URL stays exact."""
    if url.startswith("http://"):
        return "https://" + url[len("http://") :]
    return url


def load_pickups(csv_path: Path) -> tuple[list[dict], int]:
    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    # key -> record. An http URL and its https twin share a key; https wins.
    chosen: "OrderedDict[str, dict]" = OrderedDict()
    for row in rows:
        raw_url = (row.get("url") or "").strip()
        if not raw_url:
            continue
        rank_raw = (row.get("host_page_rank") or "").strip()
        rank = int(rank_raw) if rank_raw.isdigit() else None
        name = decode_name(row.get("host_name") or "")
        source = "host_name" if name else "domain"
        if not name:
            name = domain_label(raw_url)
        incoming = {
            "name": name,
            "url": raw_url,
            "rank": rank,
            "source": source,
            "https": raw_url.startswith("https://"),
        }
        existing = chosen.get(scheme_key(raw_url))
        if existing is None:
            chosen[scheme_key(raw_url)] = incoming
            continue
        # Prefer the https URL when both schemes were reported.
        if incoming["https"] and not existing["https"]:
            incoming["name"] = existing["name"] if existing["source"] == "host_name" and source != "host_name" else name
            incoming["source"] = existing["source"] if existing["source"] == "host_name" and source != "host_name" else source
            incoming["rank"] = existing["rank"] if existing["source"] == "host_name" and source != "host_name" else rank
            chosen[scheme_key(raw_url)] = incoming
        elif existing["source"] != "host_name" and source == "host_name":
            existing["name"] = name
            existing["source"] = source
            existing["rank"] = rank

    pickups = [
        {
            "name": record["name"],
            "url": record["url"],
            "rank": record["rank"],
            "source": record["source"],
        }
        for record in chosen.values()
    ]

    def sort_key(item: dict) -> tuple:
        rank = item["rank"]
        return (rank is None, -(rank or 0), item["name"].casefold(), item["url"])

    pickups.sort(key=sort_key)
    return pickups, len(rows)


def featured_from(pickups: list[dict]) -> list[dict]:
    by_name = {}
    for item in pickups:
        if item["source"] != "host_name":
            continue
        # First (highest rank) wins if a name ever repeats.
        by_name.setdefault(item["name"], item)
    missing = [name for name in FEATURED_NAMES if name not in by_name]
    if missing:
        raise SystemExit("Featured names missing from report: " + ", ".join(missing))
    chosen = [by_name[name] for name in FEATURED_NAMES]
    chosen.sort(key=lambda item: (-(item["rank"] or 0), item["name"].casefold(), item["url"]))
    return chosen


def render_section(pickups: list[dict], featured: list[dict], named_count: int) -> str:
    def link(item: dict) -> str:
        name = html.escape(item["name"], quote=True)
        url = html.escape(item["url"], quote=True)
        return f'<a href="{url}" rel="noopener">{name}</a>'

    featured_items = "\n".join(f"      <li>{link(item)}</li>" for item in featured)

    groups: "OrderedDict[object, list]" = OrderedDict()
    for item in pickups:
        groups.setdefault(item["rank"], []).append(item)

    group_html = []
    for rank, items in groups.items():
        label = "Page rank not reported" if rank is None else f"Page rank {rank}"
        lis = "\n".join(f"        <li>{link(item)}</li>" for item in items)
        group_html.append(
            f"""    <h3 class="press-rank">{html.escape(label)}</h3>
    <ul class="press-links">
{lis}
    </ul>"""
        )

    title = html.escape(RELEASE_TITLE)
    release = html.escape(RELEASE_URL, quote=True)
    media = html.escape(MEDIA_URL, quote=True)
    site = html.escape(SITE_URL, quote=True)
    groups_joined = "\n".join(group_html)
    return f"""    <p class="eyebrow">As featured in</p>
    <h2>In the press</h2>
    <p class="press-lead"><a href="{release}" rel="noopener">{title}</a></p>
    <p class="press-meta"><span class="tag">{RELEASE_DATE_DISPLAY}</span> · <a href="{media}" rel="noopener">Press Advantage</a> · <a href="{site}" rel="noopener">BanVoyage.com</a></p>
    <h3>Featured outlets</h3>
    <p>The strongest newspaper, television, and market pickups, ordered by page rank.</p>
    <ul class="reviews" id="featured-outlets">
{featured_items}
    </ul>
    <p class="press-count">Picked up by {named_count} news sites.</p>
    <details class="press-all" id="all-pickups">
      <summary>All {len(pickups)} pickup links</summary>
      <p>Every pickup URL from the November 3, 2026 distribution report, one link per URL. Outlets with no name in the report are labeled by domain. Higher page rank is listed first.</p>
{groups_joined}
    </details>"""


def render_jsonld(featured: list[dict]) -> str:
    article = {
        "@type": "NewsArticle",
        "@id": ARTICLE_ID,
        "headline": RELEASE_TITLE,
        "datePublished": RELEASE_DATE,
        "inLanguage": "en-US",
        "url": RELEASE_URL,
        "mainEntityOfPage": RELEASE_URL,
        "about": {"@id": "https://banvoyage.com/#Organization"},
        "publisher": {
            "@type": "Organization",
            "name": "Press Advantage",
            "url": "https://pressadvantage.com/",
        },
    }
    item_list = {
        "@type": "ItemList",
        "@id": LIST_ID,
        "name": "Featured press pickups for the BanVoyage launch release",
        "numberOfItems": len(featured),
        "itemListOrder": "https://schema.org/ItemListOrderDescending",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": index,
                "name": item["name"],
                "url": item["url"],
            }
            for index, item in enumerate(featured, start=1)
        ],
    }
    graph = {
        "@context": "https://schema.org",
        "@graph": [article, item_list],
    }
    body = json.dumps(graph, indent=2, ensure_ascii=False)
    return (
        "<!-- PRESS-JSONLD-START -->\n"
        '<script type="application/ld+json">\n'
        f"{body}\n"
        "</script>\n"
        "<!-- PRESS-JSONLD-END -->"
    )


CSS = """
.press-lead { font-family: "Playfair Display", Georgia, serif; font-size: clamp(1.35rem, 1.1rem + 0.8vw, 1.75rem); line-height: 1.25; margin: 0 0 8px; }
.press-meta { margin: 0 0 8px; }
.press-count { font-weight: 600; margin: 4px 0 0; }
details.press-all { margin-top: 22px; border-top: 3px double var(--stamp); }
details.press-all > summary { cursor: pointer; font-weight: 600; padding: 14px 0; }
details.press-all > summary:hover { color: var(--stamp-ink); }
h3.press-rank { font-family: Inter, system-ui, sans-serif; font-size: 0.75rem; font-weight: 600; letter-spacing: 0.14em; text-transform: uppercase; color: var(--muted); margin: 20px 0 0; }
.press-links { list-style: none; padding: 0; margin: 0 0 8px; display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 0 28px; }
.press-links li { padding: 7px 0; border-bottom: 1px solid var(--line); }
"""


def insert_css(page: str) -> str:
    needle = "@media (max-width: 820px)"
    if needle not in page:
        raise SystemExit("Could not find the stylesheet breakpoint to insert press CSS")
    page = re.sub(r"\n\.press-lead \{.*?\n\.press-links li \{[^}]+\}\n", "\n", page, count=1, flags=re.S)
    return page.replace(needle, CSS + needle, 1)


def replace_section(page: str, section_inner: str) -> str:
    section = (
        '<section class="block" id="in-the-press">\n'
        '  <div class="wrap">\n'
        "<!-- PRESS-COVERAGE-START -->\n"
        f"{section_inner}\n"
        "<!-- PRESS-COVERAGE-END -->\n"
        "  </div>\n"
        "</section>"
    )
    updated, count = re.subn(
        r'<section class="block" id="in-the-press">.*?</section>',
        section,
        page,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise SystemExit("Could not replace the in-the-press section")
    return updated


def replace_press_release(page: str) -> str:
    article = f"""    <article class="card">
      <p class="eyebrow">{RELEASE_DATE_DISPLAY}</p>
      <h3><a href="{html.escape(RELEASE_URL, quote=True)}" rel="noopener">{html.escape(RELEASE_TITLE)}</a></h3>
      <p>Launch release from Brooke and Laurence Banville, distributed by Press Advantage. BanVoyage is at <a href="{html.escape(SITE_URL, quote=True)}" rel="noopener">BanVoyage.com</a>. <a href="{html.escape(MEDIA_URL, quote=True)}" rel="noopener">BanVoyage on Press Advantage</a>.</p>
    </article>"""
    if RELEASE_URL in page.split('id="in-the-press"')[0]:
        # Already rendered above the coverage section.
        pattern = r'    <article class="card">\n      <p class="eyebrow">November 3, 2026</p>.*?</article>'
        updated, count = re.subn(pattern, article, page, count=1, flags=re.S)
        if count != 1:
            raise SystemExit("Press release card was present but could not be refreshed")
        return updated
    pattern = r'    <div class="empty">\n      <p><strong>BanVoyage\u2019s first press release is being distributed now\.</strong>.*?</div>'
    updated, count = re.subn(pattern, article, page, count=1, flags=re.S)
    if count != 1:
        raise SystemExit("Could not replace the press-release placeholder")
    return updated


def replace_jsonld(page: str, block: str) -> str:
    if "<!-- PRESS-JSONLD-START -->" in page:
        updated, count = re.subn(
            r"<!-- PRESS-JSONLD-START -->.*?<!-- PRESS-JSONLD-END -->",
            block,
            page,
            count=1,
            flags=re.S,
        )
        if count != 1:
            raise SystemExit("Could not refresh the press JSON-LD block")
        return updated
    needle = "</head>"
    if needle not in page:
        raise SystemExit("Could not find </head>")
    return page.replace(needle, block + "\n" + needle, 1)


def patch_schema_refs(page: str) -> str:
    if ARTICLE_ID not in page.split("<!-- PRESS-JSONLD-START -->")[0]:
        page = page.replace(
            '"dateModified": "2026-11-02"',
            f'"dateModified": "{PAGE_MODIFIED}"',
            1,
        )
        old_subject = """      "subjectOf": [
        {
          "@id": "https://laurence-lpblg.github.io/banvoyage-press/#WebPage"
        }
      ],"""
        new_subject = """      "subjectOf": [
        {
          "@id": "https://laurence-lpblg.github.io/banvoyage-press/#WebPage"
        },
        {
          "@id": "%s"
        }
      ],""" % ARTICLE_ID
        if old_subject not in page:
            raise SystemExit("Could not update Organization subjectOf")
        page = page.replace(old_subject, new_subject, 1)

        old_mentions = """        {
          "@id": "https://laurence-lpblg.github.io/banvoyage-press/#ApukkaRoomTour"
        }
      ],
      "primaryImageOfPage":"""
        new_mentions = """        {
          "@id": "https://laurence-lpblg.github.io/banvoyage-press/#ApukkaRoomTour"
        },
        {
          "@id": "%s"
        }
      ],
      "primaryImageOfPage":""" % ARTICLE_ID
        if old_mentions not in page:
            raise SystemExit("Could not update WebPage mentions")
        page = page.replace(old_mentions, new_mentions, 1)

        old_has = """        {
          "@id": "https://laurence-lpblg.github.io/banvoyage-press/#ApukkaRoomTour"
        }
      ],
      "breadcrumb":"""
        new_has = """        {
          "@id": "https://laurence-lpblg.github.io/banvoyage-press/#ApukkaRoomTour"
        },
        {
          "@id": "%s"
        }
      ],
      "breadcrumb":""" % LIST_ID
        if old_has not in page:
            raise SystemExit("Could not update WebPage hasPart")
        page = page.replace(old_has, new_has, 1)

        old_links = """        "https://www.facebook.com/the.banvoyage"
      ],
      "relatedLink":"""
        new_links = """        "https://www.facebook.com/the.banvoyage",
        "%s",
        "%s"
      ],
      "relatedLink":""" % (RELEASE_URL, MEDIA_URL)
        if old_links not in page:
            raise SystemExit("Could not update significantLink")
        page = page.replace(old_links, new_links, 1)
    page = page.replace(
        "Last updated November 2, 2026.",
        "Last updated November 4, 2026.",
    )
    return page


def main() -> None:
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV
    pickups, row_count = load_pickups(csv_path)
    featured = featured_from(pickups)
    named_count = sum(1 for item in pickups if item["source"] == "host_name")
    unnamed_count = sum(1 for item in pickups if item["source"] == "domain")

    payload = {
        "release": {
            "title": RELEASE_TITLE,
            "date": RELEASE_DATE,
            "dateDisplay": RELEASE_DATE_DISPLAY,
            "url": RELEASE_URL,
            "mediaPage": MEDIA_URL,
            "site": SITE_URL,
        },
        "counts": {
            "reportRows": row_count,
            "pickupLinks": len(pickups),
            "namedOutlets": named_count,
            "unlabeledPickups": unnamed_count,
            "featured": len(featured),
        },
        "featured": [
            {"name": item["name"], "url": item["url"], "rank": item["rank"]}
            for item in featured
        ],
        "pickups": pickups,
    }
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    page = INDEX.read_text(encoding="utf-8")
    page = insert_css(page)
    page = replace_section(page, render_section(pickups, featured, named_count))
    page = replace_press_release(page)
    page = replace_jsonld(page, render_jsonld(featured))
    page = patch_schema_refs(page)
    INDEX.write_text(page, encoding="utf-8")

    urls = [item["url"] for item in pickups]
    if len(urls) != len(set(urls)):
        raise SystemExit("Duplicate URLs remained after dedupe")
    if row_count != 704 or len(pickups) != 704:
        raise SystemExit(f"Expected 704 rows and links, got rows={row_count} links={len(pickups)}")
    if named_count != 461 or unnamed_count != 243:
        raise SystemExit(f"Unexpected outlet counts named={named_count} unlabeled={unnamed_count}")
    if len(featured) != 30:
        raise SystemExit(f"Expected 30 featured outlets, got {len(featured)}")

    print(f"rows {row_count}")
    print(f"pickup links {len(pickups)}")
    print(f"named outlets {named_count}")
    print(f"unlabeled pickups {unnamed_count}")
    print(f"featured {len(featured)}")
    print("top 10:")
    for item in featured[:10]:
        print(f"  {item['rank']:>3}  {item['name']}")


if __name__ == "__main__":
    main()
