# -*- coding: utf-8 -*-
"""
Lokaler Begriffsindex und Artikel-Cache (SQLite in user_files/).

Der Index baut sich beim Lernen von selbst auf: Begriffe von gelernten Karten
werden im Hintergrund einmal gegen die API geprüft und das Ergebnis dauerhaft
gespeichert. Dadurch bleibt die Zahl der Anfragen klein und die Markierung
funktioniert danach offline.
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
import time

SCHEMA_VERSION = 2

_LETTERS = "A-Za-zÄÖÜäöüßÀ-ÿ"
# Beginnt mit einem Buchstaben, darf aber Ziffern enthalten, damit
# Abkürzungen wie "T3", "IL-6", "HbA1c" oder "CD4" ganz erfasst werden.
_WORD_RE = re.compile(r"[%s][%s0-9\-']*" % (_LETTERS, _LETTERS))
_TAG_RE = re.compile(r"<[^>]+>")
_CLOZE_RE = re.compile(r"\{\{c\d+::(.*?)(?:::.*?)?\}\}", re.S)
_ENTITY_RE = re.compile(r"&(?:#\d+|#x[0-9a-fA-F]+|[a-zA-Z]+);")

# Häufige deutsche Wörter, die großgeschrieben am Satzanfang stehen oder
# als Fachbegriff nichts taugen. Verhindert unnötige API-Anfragen.
STOPWORDS = {
    # Bindewörter und Präpositionen – sie beenden eine Wortkette.
    "und", "oder", "sowie", "als", "an", "am", "bei", "beim", "im", "in",
    "ist", "sei", "je", "pro", "zu", "so", "da", "es", "man", "hat",
    "hatte", "wurde", "worden", "nun", "etc", "bzw", "vgl", "ggf", "ca",
    "aber", "alle", "allen", "aller", "alles", "also", "andere", "anderen",
    "auch", "auf", "aus", "außer", "beide", "bereits", "besonders",
    "bildet", "bilden", "bildung", "bis", "dabei", "damit", "danach", "dann",
    "daraus", "darin", "das", "dass", "davon", "dazu", "dem", "den", "denn",
    "der", "des", "deshalb", "die", "dies", "diese", "diesem", "diesen",
    "dieser", "dieses", "doch", "dort", "durch", "eine", "einem", "einen",
    "einer", "eines", "einige", "entsteht", "entstehen", "erst", "erste",
    "ersten", "etwa", "etwas", "fall", "fälle", "folge", "folgende", "für",
    "ganz", "geht", "gibt", "haben", "halten", "hier", "hoch", "ihre",
    "ihrem", "ihren", "ihrer", "immer", "jede", "jeden", "jeder", "jedoch",
    "kann", "kein", "keine", "klinik", "können", "lassen", "liegt", "mehr",
    "mehrere", "mein", "meist", "meisten", "mit", "muss", "müssen", "nach",
    "name", "neben", "nennt", "nicht", "noch", "nur", "oben", "oder", "ohne",
    "sehr", "sein", "seine", "seinen", "sich", "sie", "sind", "sowie",
    "später", "statt", "stelle", "stellen", "teil", "teile", "über",
    "unten", "unter", "viel", "viele", "vom", "von", "vor", "wann", "war",
    "waren", "was", "wegen", "weil", "weiter", "weitere", "weiteren",
    "welche", "welchem", "welchen", "welcher", "welches", "wenn", "werden",
    "wie", "wird", "wobei", "wodurch", "wofür", "woher", "wohin", "womit",
    "woraus", "worin", "wozu", "zum", "zur", "zwei", "zwischen",
    "quelle", "hinweis", "vorderseite", "rückseite", "abbildung", "folie",
    "seite", "woche", "wochen", "tag", "tage", "schritt", "beispiel",
    # Adjektive und Meta-Wörter, die am Satzanfang großgeschrieben stehen
    # und nie Teil eines Lexikontitels sind.
    "laut", "typische", "typischer", "typisches", "typischen", "jeweils",
    "eigene", "eigenen", "eigener", "eigenes", "gemeinsame", "gemeinsamer",
    "gemeinsames", "getrennte", "getrennter", "getrenntes", "griechische",
    "griechischer", "lateinische", "lateinischer", "richtung", "innerhalb",
    "außerhalb", "merkmale", "merkmal", "aufbau", "ablauf", "beginn",
    "ende", "dauer", "anzahl", "klinik", "definition", "funktion",
    # In Lernkarten gern großgeschrieben hervorgehoben – keine Abkürzungen.
    "ein", "neu", "alt", "merke", "achtung", "wichtig", "beachte", "tipp",
    "info", "nein", "falsch", "richtig", "siehe", "obacht",
}

# Verbformen und Füllwörter, die nie Teil eines Fachbegriffs sind. Sie
# brechen eine Wortkette ab, damit aus "Granulosazellen bilden Progesteron"
# kein Kandidat "Granulosazellen bilden" wird.
VERB_BREAKERS = {
    "beginnt", "besteht", "bestehen", "bewirkt", "bildet", "bilden",
    "bleibt", "bleiben", "dient", "dienen", "dringt", "dringen",
    "enthält", "enthalten", "entsteht", "entstehen", "entwickelt",
    "entwickeln", "erfolgt", "erfolgen", "ergibt", "ergeben", "findet",
    "folgt", "folgen", "führt", "führen", "gehört", "gehören", "gibt",
    "hemmt", "hemmen", "heißt", "heißen", "induziert", "kommt", "kommen",
    "liegt", "liegen", "löst", "lösen", "macht", "machen", "nennt",
    "nennen", "produziert", "produzieren", "reagiert", "reift", "reifen",
    "sezerniert", "sorgt", "stammt", "stammen", "steigt", "steigen",
    "teilt", "teilen", "trennt", "umgibt", "umgeben", "verschmelzen",
    "verschmilzt", "wandelt", "wandern", "wandert", "wächst", "wachsen",
    "wirkt", "wirken", "zeigt", "zeigen", "beträgt", "besitzt",
    # Typische Verben aus Anatomievorlesungen. Ohne sie hinge an
    # "M. biceps brachii" noch ein "beugt".
    "beugt", "beugen", "streckt", "strecken", "hebt", "heben", "senkt",
    "senken", "dreht", "drehen", "zieht", "ziehen", "innerviert",
    "innervieren", "versorgt", "versorgen", "verläuft", "verlaufen",
    "entspringt", "entspringen", "setzt", "ansetzt", "inseriert",
    "abduziert", "adduziert", "rotiert", "flektiert", "extendiert",
    "supiniert", "proniert", "reißt", "spannt", "schließt", "öffnet",
    "stabilisiert", "begrenzt", "durchzieht", "kreuzt", "teilt",
    "tastbar", "sichtbar", "beteiligt", "zuständig", "verantwortlich",
}

# Kleingeschriebene Wörter, die in Fachbegriffen vorkommen dürfen
# ("Corpus luteum", "Tuba uterina", "Zona pellucida").
_LOWER_TOKEN_RE = re.compile(r"^[a-zäöüß][a-zäöüß\-]{2,}$")
_UPPER_TOKEN_RE = re.compile(r"^[A-ZÄÖÜ][%s\-']*$" % _LETTERS)
# Gewöhnliches großgeschriebenes Wort, z. B. "Knoten" in "Hensen-Knoten".
_NORMAL_WORD_RE = re.compile(r"^[A-ZÄÖÜ][a-zäöüß]+$")

# Übliche anatomische Abkürzungen mit Punkt, Singular wie Plural.
# "M. biceps brachii" wird dadurch als ein Begriff erkannt und zusätzlich
# zur Vollform "Musculus biceps brachii" aufgelöst.
ANAT_ABBREV = {
    "m": "Musculus", "mm": "Musculi",
    "a": "Arteria", "aa": "Arteriae",
    "v": "Vena", "vv": "Venae",
    "n": "Nervus", "nn": "Nervi",
    "lig": "Ligamentum", "ligg": "Ligamenta",
    "art": "Articulatio", "artt": "Articulationes",
    "r": "Ramus", "rr": "Rami",
    "gl": "Glandula", "gll": "Glandulae",
    "proc": "Processus", "procc": "Processus",
    "nucl": "Nucleus", "ncl": "Nucleus", "nucll": "Nuclei",
    "for": "Foramen", "forr": "Foramina",
    "tub": "Tuberculum", "tr": "Tractus", "trunc": "Truncus",
    "sin": "Sinus", "fasc": "Fasciculus", "lam": "Lamina",
    "lob": "Lobus", "can": "Canalis", "vag": "Vagina",
    "vent": "Ventriculus", "seg": "Segmentum", "pl": "Plexus",
    "gangl": "Ganglion", "bur": "Bursa", "cav": "Cavitas",
    "artic": "Articulatio", "ggl": "Ganglion",
}

# Lateinische Kopfwörter. Steht eines davon vorn, ist das Folgewort
# lateinisch, auch wenn seine Endung untypisch aussieht ("biceps").
ANAT_HEADS = {
    "musculus", "musculi", "arteria", "arteriae", "vena", "venae",
    "nervus", "nervi", "ligamentum", "ligamenta", "articulatio",
    "articulationes", "ramus", "rami", "glandula", "glandulae",
    "processus", "nucleus", "nuclei", "foramen", "foramina", "os", "ossa",
    "tractus", "truncus", "tuberculum", "sinus", "fasciculus", "lamina",
    "lobus", "canalis", "vagina", "ventriculus", "segmentum", "plexus",
    "ganglion", "bursa", "cavitas", "corpus", "caput", "pars", "facies",
    "margo", "crista", "fossa", "sulcus", "spina", "tuber", "linea",
    "angulus", "apex", "basis", "collum", "cornu", "crus", "dens",
    "discus", "fovea", "hiatus", "incisura", "meatus", "membrana",
    "nodus", "ostium", "paries", "pedunculus", "plica", "radix",
    "recessus", "rete", "septum", "stratum", "sutura", "trigonum",
    "tunica", "valva", "vestibulum", "zona", "ductus", "fascia",
    "tendo", "capsula", "cartilago", "tuberositas", "condylus",
    "epicondylus", "trochanter", "sustentaculum", "labrum", "meniscus",
    "retinaculum", "aponeurosis", "raphe", "septa", "cisterna",
}

# Geschrieben werden sie immer groß ("M.", "Lig."), deshalb keine
# Groß-/Kleinschreibtoleranz: das hielte sonst auch "u. a." für eine Arterie.
_ANAT_KEYS = sorted(
    (k[:1].upper() + k[1:] for k in ANAT_ABBREV), key=len, reverse=True
)
_ANAT_WORD = r"[a-zäöü][a-zäöüß\-]{2,}"
# Kein Treffer direkt hinter "u. a." oder "i. v." – dort steht kein Muskel.
_ANAT_RE = re.compile(
    r"(?<![A-Za-zäöü]\.\s)\b(%s)\.[ \t]*(%s(?:[ \t]+%s){0,2})"
    % ("|".join(_ANAT_KEYS), _ANAT_WORD, _ANAT_WORD)
)

# Plural-Kopfwörter und ihre Einzahl. Das Flexikon führt manche Strukturen
# nur in der Einzahl ("Musculus intercostalis externus"), auf Karten steht
# aber oft die Mehrzahl ("Mm. intercostales externi").
LATIN_PLURAL_HEADS = {
    "musculi": "Musculus", "arteriae": "Arteria", "venae": "Vena",
    "nervi": "Nervus", "ligamenta": "Ligamentum",
    "articulationes": "Articulatio", "rami": "Ramus",
    "glandulae": "Glandula", "nuclei": "Nucleus", "foramina": "Foramen",
    "ossa": "Os", "nodi": "Nodus", "sulci": "Sulcus", "plexus": "Plexus",
    "bursae": "Bursa", "fasciae": "Fascia", "laminae": "Lamina",
    "ganglia": "Ganglion", "tubercula": "Tuberculum",
}

_SHORT_FORM_RE = re.compile(r"^([A-Za-z]{1,6})(\.?)\s*(\S.*)$")


def expand_short_form(term: str) -> "str | None":
    """
    "M. biceps brachii" → "Musculus biceps brachii".

    Ohne Punkt ("Proc accessorius") nur bei Kürzeln ab drei Buchstaben,
    weil ein einzelnes "A" oder "M" ohne Punkt alles Mögliche sein kann.
    Gibt None zurück, wenn der Begriff keine Kurzform ist.
    """
    match = _SHORT_FORM_RE.match((term or "").strip())
    if not match:
        return None
    abbrev, dot, rest = match.group(1), match.group(2), match.group(3).strip()
    if not abbrev[:1].isupper() or not rest:
        return None
    full = ANAT_ABBREV.get(abbrev.lower())
    if not full:
        return None
    if not dot and len(abbrev) < 3:
        return None
    if not rest[:1].islower():
        return None  # "Art. 5 Grundgesetz", "M. Meier"
    return "%s %s" % (full, " ".join(rest.split()))


_LATIN_SINGULAR_RULES = (
    ("ales", "alis"), ("ares", "aris"), ("ores", "or"), ("es", "is"),
    ("ae", "a"), ("ii", "ius"), ("i", "us"), ("a", "um"),
)


def singularize_latin(term: str) -> "str | None":
    """
    "Musculi intercostales externi" → "Musculus intercostalis externus".

    Nur ein Vorschlag: ob es den Artikel gibt, entscheidet die Prüfung gegen
    das Flexikon. Genitive ("costarum") bleiben unverändert.
    """
    words = (term or "").split()
    if len(words) < 2:
        return None
    head = LATIN_PLURAL_HEADS.get(words[0].lower())
    if not head or head.lower() == words[0].lower():
        return None
    out = [head]
    for word in words[1:]:
        low = word.lower()
        if low.endswith(("orum", "arum", "ium", "um", "us", "is")):
            out.append(word)  # Genitiv oder schon Einzahl
            continue
        for suffix, repl in _LATIN_SINGULAR_RULES:
            if low.endswith(suffix) and len(word) > len(suffix) + 1:
                word = word[: len(word) - len(suffix)] + repl
                break
        out.append(word)
    return " ".join(out)


# Endungen, die auf eine lateinische/anatomische Form hindeuten. Solche
# Ketten werden bei der Prüfung bevorzugt behandelt.
_LATIN_ENDINGS = (
    "um", "us", "is", "ae", "ii", "ri", "na", "ca", "ta", "da", "ma",
    "la", "ra", "sa", "va", "ea", "ia", "oris", "atis", "icus", "ica",
    "icum", "ina", "inum", "ans", "ens", "osus", "osa", "osum", "alis",
    "ale", "aris", "are", "ior", "ius", "eum", "ea", "oideus", "oidea",
    "oideum", "externa", "interna", "major", "minor", "dexter", "sinister",
)

# Satz- und Gliederungszeichen, an denen eine Wortkette endet. Dazu gehören
# Pfeile (→, ⇒ …), wie sie in Lernkarten ständig vorkommen, und der
# Zeilenumbruch, den strip_field_html für Blockgrenzen einsetzt.
_SEGMENT_SPLIT_RE = re.compile(
    r"[.,;:!?()\[\]{}/«»„“”\"'`|•·×÷+=<>~^#%&@$§*\n\r"
    r"–—…←-⇿•■-◿]+"
)

# Blockelemente trennen Gedanken; sie werden zu Zeilenumbrüchen, damit keine
# Wortkette über sie hinweg entsteht ("Embryoblast<br>Äußere Zellschicht").
_BLOCK_TAG_RE = re.compile(
    r"</?(?:br|p|div|li|ul|ol|dl|dt|dd|tr|td|th|table|thead|tbody|hr|"
    r"h[1-6]|blockquote|section|article|figcaption|caption|pre)\b[^>]*>",
    re.I,
)


def strip_field_html(text: str) -> str:
    """
    Macht aus Anki-Feld-/Karten-HTML reinen Text. Blockgrenzen bleiben als
    Zeilenumbruch erhalten, damit Wortketten sie nicht überspringen.
    """
    if not text:
        return ""
    text = _CLOZE_RE.sub(r"\1", text)
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "\n", text, flags=re.I | re.S)
    text = _BLOCK_TAG_RE.sub("\n", text)
    text = _TAG_RE.sub(" ", text)  # übrige Inline-Tags trennen nicht
    text = _ENTITY_RE.sub(" ", text)
    text = text.replace(" ", " ")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"[ \t]*[\r\n]+[ \t]*", "\n", text)
    return text.strip()


def is_abbreviation(token: str) -> bool:
    """
    Erkennt medizinische Abkürzungen: FSME, FSH, LH, ZNS, hCG, mRNA, pH,
    T3, T4, IL-6, CD4, HbA1c, IgG, GnRH.

    Abgegrenzt gegen normal großgeschriebene Wörter ("Corpus", "Herz"), die
    genau einen Großbuchstaben am Anfang haben.
    """
    if not token or " " in token:
        return False  # Wortketten sind nie Abkürzungen
    parts = [p for p in token.split("-") if p]
    if not parts:
        return False
    # Zusammensetzungen aus gewöhnlichen Wörtern ("Hensen-Knoten",
    # "Vater-Pacini-Körperchen") sind keine Abkürzungen.
    if len(parts) > 1 and all(_NORMAL_WORD_RE.match(p) for p in parts):
        return False
    core = "".join(parts).replace("'", "")
    if not 2 <= len(core) <= 16:
        return False
    letters = [c for c in core if c.isalpha()]
    if not letters:
        return False
    has_digit = any(c.isdigit() for c in core)
    if len(letters) < 2 and not has_digit:
        return False
    uppers = sum(1 for c in letters if c.isupper())
    inner_upper = any(c.isupper() for c in core[1:])
    # Zwei Großbuchstaben (FSH), ein Großbuchstabe im Wortinneren (hCG, pH)
    # oder Großbuchstabe plus Ziffer (T3).
    return uppers >= 2 or inner_upper or (has_digit and uppers >= 1)


def _looks_latin(token: str) -> bool:
    low = token.lower()
    return any(low.endswith(end) for end in _LATIN_ENDINGS)


def _blocks_chain(token: str) -> bool:
    low = token.lower()
    return low in STOPWORDS or low in VERB_BREAKERS


def extract_candidates(
    text: str, max_terms: int = 40, max_chain: int = 3
) -> list:
    """
    Zieht Kandidaten-Fachbegriffe aus Kartentext.

    Erkannt werden einzelne großgeschriebene Wörter sowie Wortketten mit bis
    zu `max_chain` Gliedern, etwa "Corpus luteum", "Corpus luteum gravidarum",
    "Arteria carotis interna" oder "Morbus Crohn".

    Ketten enden an Satzzeichen, Stoppwörtern und Verbformen, damit aus
    "Granulosazellen bilden Progesteron" kein Kandidat "Granulosazellen
    bilden" entsteht.

    Die Rückgabe ist nach Nützlichkeit sortiert: zuerst lateinisch wirkende
    Mehrwortbegriffe, dann übrige Ketten, zuletzt Einzelwörter – jeweils die
    längsten zuerst.
    """
    plain = strip_field_html(text)
    if not plain:
        return []

    max_chain = max(1, min(int(max_chain or 1), 4))
    seen = set()
    scored = []

    def add(term: str, priority: int) -> None:
        key = term.lower()
        if key in seen or key in STOPWORDS:
            return
        seen.add(key)
        scored.append((priority, -len(term.split()), -len(term), term))

    # Erst die anatomischen Kurzformen mit Punkt ("M. biceps brachii").
    # Sie müssen vor dem Zerlegen an Satzzeichen gefunden werden, weil der
    # Punkt sonst die Wortkette zerschneidet.
    for match in _ANAT_RE.finditer(plain):
        abbrev = match.group(1)
        words_after = []
        for word in match.group(2).split():
            if _blocks_chain(word):
                break  # "… und", "… sind", "… beugt" gehören nicht dazu
            words_after.append(word)
        if not words_after:
            continue  # "u. a. durch …" ist kein Muskel
        # Kandidat ist die Schreibweise der Karte. Welcher Artikel dahinter
        # steht ("Musculus biceps brachii"), klärt die Prüfung und merkt es
        # sich als Verweis. Alle Längen anbieten; die längste vorhandene
        # gewinnt später die Markierung.
        for count in range(len(words_after), 0, -1):
            add("%s. %s" % (abbrev, " ".join(words_after[:count])), 0)

    for segment in _SEGMENT_SPLIT_RE.split(plain):
        words = _WORD_RE.findall(segment)
        if not words:
            continue
        for i, word in enumerate(words):
            head = word.strip("-'")
            if not head or _blocks_chain(head):
                continue

            head_is_abbrev = is_abbreviation(head)
            latin_head = head.lower() in ANAT_HEADS
            if (
                not head_is_abbrev
                and not latin_head
                and (len(head) < 3 or not _UPPER_TOKEN_RE.match(head))
            ):
                continue
            if head.lower() in ANAT_ABBREV:
                # "Lig", "Proc", "Artt" allein bringen nichts. Ohne Punkt
                # geschrieben ("Proc accessorius") zählt die Kette trotzdem,
                # sofern das Kürzel lang genug ist, um eindeutig zu sein.
                if len(head) >= 3 and head[:1].isupper():
                    tail = []
                    for j in range(i + 1, min(i + 4, len(words))):
                        nxt = words[j].strip("-'")
                        if not _LOWER_TOKEN_RE.match(nxt) or _blocks_chain(nxt):
                            break
                        if not tail and not _looks_latin(nxt):
                            break  # "Art dieser Wirkung" ist kein Gelenk
                        tail.append(nxt)
                        add("%s %s" % (head, " ".join(tail)), 0)
                continue
            if latin_head and len(head) >= 2:
                add(head, 2)

            if head_is_abbrev:
                # Abkürzungen sind besonders nachschlagenswert und kommen
                # deshalb vor den gewöhnlichen Einzelwörtern dran.
                add(head, 1)
                # Aus "mRNA-Expression" oder "pH-Wert" auch die Abkürzung
                # selbst anbieten.
                if "-" in head:
                    first = head.split("-")[0]
                    if first != head and is_abbreviation(first):
                        add(first, 1)
            elif len(head) >= 4:
                add(head, 3)

            # Wortkette nach rechts verlängern.
            #
            # Kleingeschriebene Folgeglieder müssen lateinisch wirken
            # ("luteum", "pellucida", "uterinae"). Sonst entstünden aus
            # normalem Fließtext Ketten wie "Hormon baut" oder
            # "Zeus gebar Athene". Großgeschriebene Folgeglieder sind
            # erlaubt – sie tragen Begriffe wie "Morbus Crohn" oder
            # "Kleines Becken".
            # Nach einem lateinischen Kopfwort ist alles Folgende lateinisch,
            # auch wenn die Endung untypisch aussieht ("Musculus biceps").
            chain = [head]
            all_latin_tail = True
            for j in range(i + 1, min(i + max_chain, len(words))):
                nxt = words[j].strip("-'")
                if len(nxt) < 2 or _blocks_chain(nxt):
                    break
                if _LOWER_TOKEN_RE.match(nxt):
                    if not (latin_head or _looks_latin(nxt)):
                        break
                elif _UPPER_TOKEN_RE.match(nxt) or is_abbreviation(nxt):
                    # trägt "Vitamin B12", "Faktor VIII", "Morbus Crohn"
                    all_latin_tail = False
                else:
                    break
                chain.append(nxt)
                add(" ".join(chain), 0 if all_latin_tail else 2)

    scored.sort()
    return [entry[3] for entry in scored[:max_terms]]


class Store:
    """SQLite-Backend. Thread-sicher über ein Lock."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS terms (
                    term_key TEXT PRIMARY KEY,
                    term     TEXT NOT NULL,
                    exists_  INTEGER NOT NULL,
                    checked  REAL NOT NULL,
                    target   TEXT
                );
                CREATE TABLE IF NOT EXISTS articles (
                    title_key TEXT PRIMARY KEY,
                    payload   TEXT NOT NULL,
                    fetched   REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS meta (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                );
                """
            )
            columns = {
                row[1] for row in self._conn.execute("PRAGMA table_info(terms)")
            }
            if "target" not in columns:
                self._conn.execute("ALTER TABLE terms ADD COLUMN target TEXT")
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key='schema'"
            ).fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO meta(key, value) VALUES('schema', ?)",
                    (str(SCHEMA_VERSION),),
                )
            else:
                try:
                    old = int(row[0])
                except (TypeError, ValueError):
                    old = 1
                if old < 2:
                    # Bis Version 1 wurde nur der wörtliche Titel geprüft.
                    # "M. biceps brachii" oder "Oozyten" stehen deshalb als
                    # "gibt es nicht" im Index. Diese Einträge müssen neu
                    # geprüft werden, jetzt mit Auflösung zur Vollform.
                    self._conn.execute("DELETE FROM terms WHERE exists_=0")
                if old != SCHEMA_VERSION:
                    self._conn.execute(
                        "UPDATE meta SET value=? WHERE key='schema'",
                        (str(SCHEMA_VERSION),),
                    )
            self._conn.commit()

    # ---------------- Begriffe ----------------

    def resolve_terms(self, terms: list) -> tuple:
        """
        Teilt Begriffe in (bekannt: {Schreibweise: Artikel}, ungeprüft) auf.

        Der Artikel ist meist die Schreibweise selbst. Bei Kurzformen und
        gebeugten Formen ist es der Titel, der dafür geöffnet wird:
        "M. biceps brachii" → "Musculus biceps brachii", "Oozyten" → "Oozyte".
        Bekannt-nicht-vorhanden fällt stillschweigend weg.
        """
        if not terms:
            return {}, []
        keys = list({t.lower() for t in terms})
        known = {}
        with self._lock:
            for start in range(0, len(keys), 400):
                chunk = keys[start:start + 400]
                rows = self._conn.execute(
                    "SELECT term_key, exists_, target FROM terms "
                    "WHERE term_key IN (%s)" % ",".join("?" * len(chunk)),
                    chunk,
                ).fetchall()
                for key, exists, target in rows:
                    known[key] = (exists, target)
        found, unknown = {}, []
        for term in terms:
            state = known.get(term.lower())
            if state is None:
                unknown.append(term)
            elif state[0]:
                found[term] = state[1] or term
        return found, unknown

    def lookup_terms(self, terms: list) -> tuple:
        """Wie resolve_terms, aber nur die Liste der bekannten Schreibweisen."""
        found, unknown = self.resolve_terms(terms)
        return list(found), unknown

    def record_term(self, term: str, exists: bool, target: "str | None" = None) -> None:
        self.record_terms([(term, exists, target)])

    def record_terms(self, entries) -> None:
        """
        Schreibt viele Begriffe in einer einzigen Transaktion. Der Index
        wird dadurch nur einmal kurz gesperrt statt einmal pro Begriff.

        Einträge sind (Begriff, vorhanden) oder (Begriff, vorhanden, Artikel).
        """
        now = time.time()
        rows = []
        for entry in entries:
            term, exists = entry[0], entry[1]
            target = entry[2] if len(entry) > 2 else None
            if not term:
                continue
            if not exists or not target or target.lower() == term.lower():
                target = None
            rows.append((term.lower(), term, 1 if exists else 0, now, target))
        if not rows:
            return
        with self._lock:
            self._conn.executemany(
                "INSERT OR REPLACE INTO terms"
                "(term_key, term, exists_, checked, target) VALUES(?,?,?,?,?)",
                rows,
            )
            self._conn.commit()

    def forget_negative_terms(self) -> int:
        with self._lock:
            cur = self._conn.execute("DELETE FROM terms WHERE exists_=0")
            self._conn.commit()
            return cur.rowcount

    def stats(self) -> dict:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM terms").fetchone()[0]
            hits = self._conn.execute(
                "SELECT COUNT(*) FROM terms WHERE exists_=1"
            ).fetchone()[0]
            aliases = self._conn.execute(
                "SELECT COUNT(*) FROM terms WHERE exists_=1 AND target IS NOT NULL"
            ).fetchone()[0]
            cached = self._conn.execute(
                "SELECT COUNT(*) FROM articles"
            ).fetchone()[0]
        return {
            "geprueft": total,
            "vorhanden": hits,
            "verweise": aliases,
            "artikel_cache": cached,
        }

    # ---------------- Artikel ----------------

    def get_article(self, title: str, max_age: float) -> "dict | None":
        """max_age <= 0 schaltet den Zwischenspeicher ab (siehe config.md)."""
        import json

        if max_age <= 0:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT payload, fetched FROM articles WHERE title_key=?",
                (title.lower(),),
            ).fetchone()
        if not row:
            return None
        if time.time() - row[1] > max_age:
            return None
        try:
            return json.loads(row[0])
        except ValueError:
            return None

    def put_article(self, title: str, payload: dict) -> None:
        import json

        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO articles(title_key, payload, fetched) "
                "VALUES(?,?,?)",
                (title.lower(), json.dumps(payload), time.time()),
            )
            self._conn.commit()

    def clear_articles(self) -> int:
        with self._lock:
            cur = self._conn.execute("DELETE FROM articles")
            self._conn.commit()
            return cur.rowcount

    def clear_all(self) -> None:
        with self._lock:
            self._conn.executescript(
                "DELETE FROM terms; DELETE FROM articles;"
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass
