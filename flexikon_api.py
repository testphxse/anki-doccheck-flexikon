# -*- coding: utf-8 -*-
"""
Client für die dokumentierte DocCheck-Flexikon-API.

Endpunkte laut https://flexikon.doccheck.com/llms-full.txt (Stand: Okt 2026):
  Artikel     GET https://flexikon.doccheck.com/api.php
              ?page=<Titel>&action=parse&format=json&prop=text|sections|displaytitle
  Suche       GET https://search.doccheck.com/doccheck-portal/search
              ?q=<Begriff>&language=de&facetq=content_type:flexikon
  Kategorien  GET https://flexikon.doccheck.com/rest.php/flexikon/v1/article/categories
              ?articleTitle=<Titel>

Die Doku bittet darum, den Bot mit einem aussagekräftigen User-Agent zu
kennzeichnen und die Anfragerate niedrig zu halten. Beides ist unten umgesetzt.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ADDON_VERSION = "1.0.0"
USER_AGENT = (
    "AnkiFlexikonLookup/%s (Anki add-on, persoenlicher Lerngebrauch; "
    "+https://flexikon.doccheck.com/)" % ADDON_VERSION
)

API_URL = "https://flexikon.doccheck.com/api.php"
SEARCH_URL = "https://search.doccheck.com/doccheck-portal/search"
CATEGORIES_URL = "https://flexikon.doccheck.com/rest.php/flexikon/v1/article/categories"
ARTICLE_BASE = "https://flexikon.doccheck.com/de/"

DEFAULT_TIMEOUT = 12


class FlexikonError(Exception):
    """Netzwerk-/API-Fehler, den die UI dem Nutzer zeigen darf."""


class ArticleMissing(FlexikonError):
    """Der Artikel existiert nicht (MediaWiki: missingtitle / invalidtitle)."""


class _RateLimiter:
    """Einfacher Token-Bucket. Hält die Anfragerate bewusst niedrig."""

    def __init__(self, min_interval: float = 0.5) -> None:
        self._min_interval = min_interval
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delta = now - self._last
            if delta < self._min_interval:
                time.sleep(self._min_interval - delta)
            self._last = time.monotonic()

    def set_interval(self, seconds: float) -> None:
        with self._lock:
            self._min_interval = max(0.2, float(seconds))


_limiter = _RateLimiter()


def set_min_interval(seconds: float) -> None:
    _limiter.set_interval(seconds)


def _get(url: str, timeout: int = DEFAULT_TIMEOUT) -> bytes:
    _limiter.wait()
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "de",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise FlexikonError("HTTP %s für %s" % (exc.code, url)) from exc
    except urllib.error.URLError as exc:
        raise FlexikonError("Keine Verbindung: %s" % exc.reason) from exc
    except Exception as exc:  # noqa: BLE001 - alles als UI-Fehler zeigen
        raise FlexikonError(str(exc)) from exc


def _get_json(url: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    raw = _get(url, timeout=timeout)
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except ValueError as exc:
        snippet = raw[:200].decode("utf-8", "replace")
        raise FlexikonError("Antwort war kein JSON: %s" % snippet) from exc


def article_url(title: str) -> str:
    """Öffentliche Artikel-URL zum Titel."""
    return ARTICLE_BASE + urllib.parse.quote(title.replace(" ", "_"), safe="")


# Endungen, die auf eine gebeugte Form hindeuten, von der vorsichtigsten
# zur kühnsten Änderung. Lexikontitel stehen im Nominativ Singular, auf
# der Karte steht der Begriff aber oft gebeugt ("Oozyten", "Y-Chromosoms").
_INFLECTION_RULES = (
    # Eindeutige lateinische Mehrzahl zuerst, dann die häufigen deutschen
    # Endungen, zuletzt die gewagteren Ersetzungen.
    ("ien", "ium"), ("n", ""), ("s", ""), ("e", ""),
    ("em", ""), ("er", ""), ("es", ""), ("en", ""), ("ae", "a"),
    ("ens", ""), ("nen", ""), ("ern", ""),
    ("ia", "ium"), ("i", "us"), ("a", "um"),
    ("ides", "is"), ("iden", "is"),
)


def _deumlaut(word: str) -> str:
    """Hebt den Plural-Umlaut auf: Keimblätt → Keimblatt, Häls → Hals."""
    for src, dst in (
        ("äu", "au"), ("ä", "a"), ("ö", "o"), ("ü", "u"),
        ("Äu", "Au"), ("Ä", "A"), ("Ö", "O"), ("Ü", "U"),
    ):
        word = word.replace(src, dst)
    return word


def expansion_variants(term: str) -> list:
    """
    Vollformen zu einer anatomischen Kurzform, beste Vermutung zuerst.

    "M. biceps brachii"         → ["Musculus biceps brachii"]
    "Mm. intercostales externi" → ["Musculi intercostales externi",
                                   "Musculus intercostalis externus"]
    "Proc accessorius"          → ["Processus accessorius"]
    """
    from . import flexikon_store as terms

    out = []
    full = terms.expand_short_form(term)
    if full:
        out.append(full)
    singular = terms.singularize_latin(full or (term or "").strip())
    if singular and singular not in out:
        out.append(singular)
    return out


def title_variants(term: str, limit: int = 14, head_fallback: bool = True) -> list:
    """
    Titel, unter denen der Artikel zu einem Begriff stehen könnte, beste
    Vermutung zuerst. Reine Vorschläge – verwendet wird nur, was es gibt.

    "M. biceps brachii" → "Musculus biceps brachii"
    "Oozyten"           → "Oozyte", "Oozyt"
    "Y-Chromosoms"      → "Y-Chromosom"
    "Spermien"          → "Spermium", "Spermie" …
    "Corpus lutei"      → "Corpus luteus", "Corpus"

    head_fallback=False lässt das erste Glied allein ("Corpus") weg. Beim
    Markieren von Karten wäre das falsch: die ganze Kette verwiese dann auf
    einen Artikel, der nur ihr erstes Wort erklärt.
    """
    from . import flexikon_store as terms

    term = " ".join((term or "").split())
    if not term:
        return []

    out = []
    seen = {term.lower()}

    def add(candidate: str) -> None:
        candidate = candidate.strip()
        low = candidate.lower()
        if len(candidate) < 3 or low in seen:
            return
        if low in terms.STOPWORDS or low in terms.VERB_BREAKERS:
            return
        seen.add(low)
        out.append(candidate)

    expansions = expansion_variants(term)
    for candidate in expansions:
        add(candidate)
    if terms.expand_short_form(term):
        # Eine Kurzform wird nur ausgeschrieben. Deutsche Endungen daran
        # abzuschneiden ("M. biceps brachi") ergäbe nur Unsinn.
        return out[:limit]

    words = term.split()
    last = words[-1]
    head = words[:-1]

    for suffix, replacement in _INFLECTION_RULES:
        if not last.lower().endswith(suffix):
            continue
        stem = last[: len(last) - len(suffix)] + replacement
        if len(stem) < 3:
            continue
        add(" ".join(head + [stem]))
        plain = _deumlaut(stem)
        if plain != stem:
            add(" ".join(head + [plain]))

    # Bei Wortketten lohnt auch der Blick auf das erste Glied allein.
    if head_fallback and len(words) > 1:
        add(words[0])

    return out[:limit]


# --------------------------------------------------------------------------
# Artikel
# --------------------------------------------------------------------------

def fetch_article(title: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """
    Holt einen Artikel. Gibt {"title", "html", "sections", "url"} zurück.
    Wirft ArticleMissing, wenn es die Seite nicht gibt.
    """
    params = {
        "page": title,
        "action": "parse",
        "format": "json",
        "prop": "text|sections|displaytitle",
        "disabletoc": "1",
        "redirects": "1",
    }
    url = API_URL + "?" + urllib.parse.urlencode(params)
    data = _get_json(url, timeout=timeout)

    if "error" in data:
        code = str(data["error"].get("code", ""))
        if code in ("missingtitle", "invalidtitle", "nosuchpageid"):
            raise ArticleMissing(title)
        raise FlexikonError(
            "API-Fehler %s: %s" % (code, data["error"].get("info", ""))
        )

    parse = data.get("parse")
    if not parse:
        raise FlexikonError("Unerwartete Antwortstruktur (kein 'parse'-Objekt).")

    html = parse.get("text")
    if isinstance(html, dict):  # formatversion=1 liefert {"*": "..."}
        html = html.get("*", "")
    if not html:
        raise ArticleMissing(title)

    display = parse.get("displaytitle")
    if isinstance(display, dict):
        display = display.get("*", "")
    display = _strip_tags(display or parse.get("title") or title)

    return {
        "title": display,
        "raw_title": parse.get("title") or title,
        "html": html,
        "sections": parse.get("sections") or [],
        "url": article_url(parse.get("title") or title),
    }


BATCH_LIMIT = 50


def article_exists_many(titles: list, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """
    Prüft bis zu 50 Titel mit EINER Anfrage und gibt {Titel: bool} zurück.

    Nutzt 'action=query', den MediaWiki-Standard für Sammelabfragen. Der ist
    in der Flexikon-Kurzdoku nicht aufgeführt; falls er nicht verfügbar ist,
    wirft die Funktion FlexikonError und der Aufrufer fällt auf die
    dokumentierte Einzelprüfung zurück. Eine Sammelanfrage belastet den
    Server deutlich weniger als 50 Einzelabrufe.
    """
    clean = [t for t in titles if t and "|" not in t and "#" not in t]
    if not clean:
        return {}
    clean = clean[:BATCH_LIMIT]

    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "redirects": "1",
        "titles": "|".join(clean),
    }
    url = API_URL + "?" + urllib.parse.urlencode(params)
    data = _get_json(url, timeout=timeout)

    if "error" in data:
        raise FlexikonError(
            "Sammelabfrage nicht möglich: %s" % data["error"].get("code", "")
        )
    query = data.get("query")
    if not isinstance(query, dict) or "pages" not in query:
        raise FlexikonError("Sammelabfrage lieferte keine 'pages'.")

    # MediaWiki normalisiert Titel und folgt Weiterleitungen. Dieser Weg
    # wird nachgebaut, damit das Ergebnis dem angefragten Begriff zugeordnet
    # werden kann.
    current = {term: term for term in clean}
    for key in ("normalized", "redirects", "converted"):
        for entry in query.get(key) or []:
            if not isinstance(entry, dict):
                continue
            src, dst = entry.get("from"), entry.get("to")
            if not src or not dst:
                continue
            for term, now in list(current.items()):
                if now == src:
                    current[term] = dst

    by_final = {}
    for term, final in current.items():
        by_final.setdefault(final.lower(), []).append(term)

    pages = query["pages"]
    if isinstance(pages, dict):  # formatversion=1
        pages = list(pages.values())

    result = {}
    for page in pages:
        if not isinstance(page, dict):
            continue
        title = page.get("title") or ""
        exists = ("missing" not in page) and ("invalid" not in page)
        for term in by_final.get(title.lower(), []):
            result[term] = exists

    # Titel, die gar nicht in der Antwort auftauchen, bleiben ungeprüft.
    return result


def article_exists(title: str, timeout: int = DEFAULT_TIMEOUT) -> bool:
    """
    Prüft nur die Existenz. Nutzt prop=displaytitle, damit die Antwort
    so klein wie möglich bleibt.
    """
    params = {
        "page": title,
        "action": "parse",
        "format": "json",
        "prop": "displaytitle",
        "disabletoc": "1",
        "redirects": "1",
    }
    url = API_URL + "?" + urllib.parse.urlencode(params)
    data = _get_json(url, timeout=timeout)
    if "error" in data:
        code = str(data["error"].get("code", ""))
        if code in ("missingtitle", "invalidtitle", "nosuchpageid"):
            return False
        raise FlexikonError(
            "API-Fehler %s: %s" % (code, data["error"].get("info", ""))
        )
    return bool(data.get("parse"))


# --------------------------------------------------------------------------
# Suche
# --------------------------------------------------------------------------

def search(term: str, limit: int = 10, timeout: int = DEFAULT_TIMEOUT) -> list:
    """
    Volltextsuche. Gibt eine Liste von {"title", "url"} zurück.

    Das Antwortformat der Portalsuche ist in der Doku nicht beschrieben,
    deshalb werden hier mehrere plausible Strukturen abgeklopft. Schlägt das
    fehl, liefert die Funktion eine leere Liste statt einer Exception.
    """
    params = {"q": term, "language": "de", "facetq": "content_type:flexikon"}
    url = SEARCH_URL + "?" + urllib.parse.urlencode(params)
    try:
        data = _get_json(url, timeout=timeout)
    except FlexikonError:
        return []

    items = None
    for path in (
        ("results",),
        ("docs",),
        ("hits",),
        ("response", "docs"),
        ("data", "results"),
        ("resultList",),
    ):
        node = data
        ok = True
        for key in path:
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                ok = False
                break
        if ok and isinstance(node, list):
            items = node
            break

    if items is None:
        return []

    out = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        title = (
            item.get("title")
            or item.get("name")
            or item.get("headline")
            or item.get("displayTitle")
        )
        if isinstance(title, list):
            title = title[0] if title else None
        if not title:
            continue
        title = _strip_tags(str(title))
        href = item.get("url") or item.get("link") or item.get("href") or ""
        if isinstance(href, list):
            href = href[0] if href else ""
        if href and href.startswith("/"):
            href = "https://flexikon.doccheck.com" + href
        out.append({"title": title, "url": href or article_url(title)})
    return out


def fetch_categories(title: str, timeout: int = DEFAULT_TIMEOUT) -> list:
    """Tags/Kategorien eines Artikels. Fehler werden still geschluckt."""
    url = CATEGORIES_URL + "?" + urllib.parse.urlencode({"articleTitle": title})
    try:
        data = _get_json(url, timeout=timeout)
    except FlexikonError:
        return []
    if isinstance(data, list):
        raw = data
    elif isinstance(data, dict):
        raw = data.get("categories") or data.get("tags") or data.get("data") or []
    else:
        return []
    out = []
    for entry in raw:
        if isinstance(entry, str):
            out.append(entry)
        elif isinstance(entry, dict):
            name = entry.get("name") or entry.get("title") or entry.get("category")
            if name:
                out.append(str(name))
    return out


# --------------------------------------------------------------------------
# HTML-Aufbereitung
# --------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(value: str) -> str:
    return _TAG_RE.sub("", value or "").strip()


_SCRIPT_RE = re.compile(
    r"<(script|style|noscript)\b[^>]*>.*?</\1>", re.I | re.S
)
_EDITSECTION_RE = re.compile(
    r'<span class="mw-editsection".*?</span>', re.I | re.S
)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def clean_article_html(html: str) -> str:
    """
    Macht das MediaWiki-HTML für die Anzeige in Anki brauchbar:
    entfernt Skripte und Bearbeiten-Links, macht Bild- und Link-Ziele absolut
    und verdrahtet interne Links mit pycmd, damit sie im Popup aufgehen.
    """
    html = _SCRIPT_RE.sub("", html or "")
    html = _COMMENT_RE.sub("", html)
    html = _EDITSECTION_RE.sub("", html)

    def fix_src(match: "re.Match") -> str:
        attr, quote, value = match.group(1), match.group(2), match.group(3)
        if value.startswith("//"):
            value = "https:" + value
        elif value.startswith("/"):
            value = "https://flexikon.doccheck.com" + value
        return '%s=%s%s%s' % (attr, quote, value, quote)

    # Der Wert darf alles außer dem öffnenden Anführungszeichen enthalten,
    # sonst zerbrechen Titel mit Apostroph (z. B. /de/Fisher's_Test).
    html = re.sub(
        r'\b(src|srcset|poster)=(["\'])((?:(?!\2)[^>])*)\2',
        fix_src,
        html,
        flags=re.I,
    )

    def fix_href(match: "re.Match") -> str:
        quote, value = match.group(1), match.group(2)
        decoded = value.replace("&amp;", "&")
        internal = re.match(r"^/de/([^#?]+)", decoded)
        if internal:
            title = urllib.parse.unquote(internal.group(1)).replace("_", " ")
            safe = title.replace("\\", "\\\\").replace("'", "\\'")
            return (
                'href="#" data-flexikon="1" '
                "onclick=\"pycmd('flexikon-nav:%s'); return false;\"" % safe
            )
        if decoded.startswith("/"):
            decoded = "https://flexikon.doccheck.com" + decoded
        elif decoded.startswith("//"):
            decoded = "https:" + decoded
        if decoded.startswith("#"):
            return 'href=%s%s%s' % (quote, value, quote)
        safe = decoded.replace("\\", "\\\\").replace("'", "\\'")
        return (
            'href="#" '
            "onclick=\"pycmd('flexikon-ext:%s'); return false;\"" % safe
        )

    html = re.sub(
        r'href=(["\'])((?:(?!\1)[^>])*)\1', fix_href, html, flags=re.I
    )
    return html
