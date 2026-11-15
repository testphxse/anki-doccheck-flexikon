# -*- coding: utf-8 -*-
"""
DocCheck Flexikon für Anki
==========================

Markiert medizinische Fachbegriffe auf deinen Karten und schlägt sie per Klick
im DocCheck Flexikon nach – ohne die Lernsitzung zu verlassen.

Der Begriffsindex baut sich beim Lernen von selbst auf: Begriffe der gerade
gelernten Karte werden einmal im Hintergrund gegen die Flexikon-API geprüft
und das Ergebnis dauerhaft lokal gespeichert. Danach funktioniert die
Markierung sofort und offline.

Die genutzten Endpunkte sind die unter flexikon.doccheck.com/llms.txt
dokumentierten. Inhalte werden nur auf Abruf geladen und nicht auf Vorrat
gespeichert; die Rechte daran liegen bei DocCheck.
"""

from __future__ import annotations

import json
import os
import threading

from anki.hooks import wrap  # noqa: F401  (hält Legacy-Kompatibilität bereit)
from aqt import gui_hooks, mw
from aqt.qt import QAction, QKeySequence, QMenu
from aqt.utils import tooltip

from . import flexikon_api as api
from . import flexikon_store as store_mod

ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
USER_FILES = os.path.join(ADDON_DIR, "user_files")
DB_PATH = os.path.join(USER_FILES, "flexikon.db")

DEFAULTS = {
    "markierung_aktiv": True,
    "markierung_stil": "dotted",
    "doppelklick_nachschlagen": True,
    "hintergrund_pruefung": True,
    "max_wortkette": 3,
    "max_begriffe_pro_karte": 60,
    "max_pruefungen_pro_karte": 25,
    "sammelabfrage": True,
    "sofort_nachziehen": True,
    "antwort_vorbereiten": True,
    "grundform_versuchen": True,
    "anfrage_abstand_sekunden": 0.4,
    "artikel_cache_stunden": 72,
}

_store = None
_store_lock = threading.Lock()

_pending = []
_pending_lock = threading.Lock()
_worker_running = False

# Was gerade auf dem Bildschirm steht. Nur diese Karte wird nachgezogen,
# wenn die Hintergrundprüfung neue Begriffe gefunden hat.
_last_render = {"card_id": None, "side": None}


# ---------------------------------------------------------------- Grundlagen


def addon_package() -> str:
    return mw.addonManager.addonFromModule(__name__)


def get_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        user = mw.addonManager.getConfig(__name__) or {}
        cfg.update({k: v for k, v in user.items() if v is not None})
    except Exception:
        pass
    return cfg


def save_config(cfg: dict) -> None:
    try:
        mw.addonManager.writeConfig(__name__, cfg)
    except Exception:
        pass


def get_store():
    global _store
    with _store_lock:
        if _store is None:
            try:
                os.makedirs(USER_FILES, exist_ok=True)
                _store = store_mod.Store(DB_PATH)
            except Exception as exc:  # pragma: no cover - Defensive
                print("[Flexikon] Index nicht verfügbar:", exc)
                _store = None
        return _store


# ------------------------------------------------- Hintergrundprüfung


def _queue_terms(terms: list, front: bool = True) -> None:
    """
    Reiht Begriffe zur Prüfung ein. `front=True` stellt sie nach vorn: die
    gerade sichtbare Karte wird zuerst aufgelöst, auch wenn noch ein
    Rückstand aus früheren Karten wartet.
    """
    cfg = get_config()
    if not cfg.get("hintergrund_pruefung", True) or not terms:
        return
    limit = int(cfg.get("max_pruefungen_pro_karte", 25))
    with _pending_lock:
        known = set(_pending)
        fresh = [t for t in terms[:limit] if t not in known]
        if not fresh:
            return
        if front:
            _pending[:0] = fresh
        else:
            _pending.extend(fresh)
    _start_worker()


def _start_worker() -> None:
    global _worker_running
    with _pending_lock:
        if _worker_running or not _pending:
            return
        _worker_running = True
    try:
        mw.taskman.run_in_background(_worker, _worker_done)
    except Exception:
        with _pending_lock:
            _worker_running = False


MAX_CHECKS_PER_RUN = 300

# Ob die Sammelabfrage in dieser Sitzung funktioniert. None = noch offen.
_session = {"batch": None}


def _check_titles(titles: list, use_batch: bool) -> tuple:
    """
    Fragt das Flexikon, welche Titel es gibt. Rückgabe: ({Titel: bool},
    use_batch). Titel, die in der Antwort fehlen, bleiben ungeprüft.

    Bevorzugt die Sammelabfrage (bis zu 50 Titel pro Anfrage). Ist sie nicht
    verfügbar, wird auf die dokumentierte Einzelprüfung umgeschaltet. Ist
    das Netz weg, kommt die FlexikonError beim Aufrufer an.
    """
    titles = list(dict.fromkeys(t for t in titles if t))
    results = {}
    if not titles:
        return results, use_batch
    batch_failed = False
    if use_batch:
        try:
            for start in range(0, len(titles), api.BATCH_LIMIT):
                chunk = titles[start:start + api.BATCH_LIMIT]
                results.update(api.article_exists_many(chunk))
            _session["batch"] = True
            return results, True
        except api.FlexikonError as exc:
            print("[Flexikon] Sammelabfrage nicht nutzbar (%s) – "
                  "versuche Einzelprüfung." % exc)
        except Exception as exc:  # unerwartetes Antwortformat
            print("[Flexikon] Sammelabfrage fehlgeschlagen:", exc)
        batch_failed = True

    for title in titles:
        if title in results:
            continue
        results[title] = api.article_exists(title)
        if batch_failed:
            # Einzeln geht es, gesammelt nicht: für diese Sitzung merken,
            # damit nicht jede Karte erst eine vergebliche Anfrage kostet.
            _session["batch"] = False
            batch_failed = False
    return results, False


def _resolve(todo: list, store, use_batch: bool, try_forms: bool) -> tuple:
    """
    Klärt für jede Schreibweise, welcher Artikel dahintersteht.

    1. Gibt es den Begriff wörtlich als Titel?
    2. Wenn nicht: gibt es ihn ausgeschrieben oder in der Grundform?
       "M. biceps brachii" → "Musculus biceps brachii", "Oozyten" → "Oozyte".

    Rückgabe: (Einträge für den Index, use_batch, vollständig).
    Bei Netzausfall mitten in der Prüfung ist `vollständig` False; dann
    stehen nur gesicherte Treffer in den Einträgen und der Rest wird beim
    nächsten Sehen der Karte erneut versucht.
    """
    literal, use_batch = _check_titles(todo, use_batch)
    rows = []
    missing = []
    for term in todo:
        state = literal.get(term)
        if state is True:
            rows.append((term, True, None))
        elif state is False:
            missing.append(term)
    if not missing:
        return rows, use_batch, True
    if not try_forms:
        rows.extend((term, False, None) for term in missing)
        return rows, use_batch, True

    plans = {}
    for term in missing:
        if use_batch:
            plans[term] = api.title_variants(term, limit=3, head_fallback=False)
        else:
            # Ohne Sammelabfrage kostet jede Form eine eigene Anfrage. Dann
            # werden nur Kurzformen ausgeschrieben, Endungen nicht probiert.
            plans[term] = api.expansion_variants(term)[:1]
    wanted = list(dict.fromkeys(v for forms in plans.values() for v in forms))
    known, unknown_forms = store.resolve_terms(wanted)
    # Nur fragen, was nötig ist: steht die beste Vermutung schon im Index,
    # brauchen die schwächeren dahinter keine Anfrage mehr.
    open_forms = set(unknown_forms)
    unchecked = []
    for term in missing:
        for form in plans[term]:
            if form in known:
                break
            if form in open_forms and form not in unchecked:
                unchecked.append(form)
    checked = {}
    complete = True
    if unchecked:
        try:
            checked, use_batch = _check_titles(unchecked, use_batch)
        except api.FlexikonError:
            complete = False

    for term in missing:
        target = None
        open_question = False
        for form in plans[term]:
            if form in known:
                target = known[form]
                break
            state = checked.get(form)
            if state:
                target = form
                break
            if state is None and form in unchecked:
                open_question = True
        if target:
            rows.append((term, True, target))
        elif complete and not open_question:
            rows.append((term, False, None))
    # Bestätigte Vollformen sind selbst gültige Titel – gleich mit merken.
    rows.extend((form, True, None) for form, ok in checked.items() if ok)
    return rows, use_batch, complete


def _worker() -> int:
    """
    Prüft wartende Begriffe gegen die API. Läuft im Hintergrund-Thread.

    Rückgabe: Anzahl der neu gefundenen Begriffe. Nur wenn die größer als
    null ist, lohnt sich das Nachziehen der sichtbaren Karte.
    """
    checked = 0
    found_new = 0
    store = get_store()
    if store is None:
        return 0
    cfg = get_config()
    api.set_min_interval(float(cfg.get("anfrage_abstand_sekunden", 0.4)))
    use_batch = bool(cfg.get("sammelabfrage", True)) and _session["batch"] is not False
    try_forms = bool(cfg.get("grundform_versuchen", True))

    while checked < MAX_CHECKS_PER_RUN:
        with _pending_lock:
            if not _pending:
                break
            batch = []
            while _pending and len(batch) < api.BATCH_LIMIT:
                batch.append(_pending.pop(0))

        _known, todo = store.resolve_terms(batch)
        if not todo:
            continue
        try:
            rows, use_batch, complete = _resolve(todo, store, use_batch, try_forms)
        except api.FlexikonError:
            break  # Netz weg: beim nächsten Sehen der Karte erneut
        except Exception as exc:
            print("[Flexikon] Prüfung fehlgeschlagen:", exc)
            break
        store.record_terms(rows)
        wanted = {t.lower() for t in todo}
        found_new += sum(1 for row in rows if row[1] and row[0].lower() in wanted)
        checked += len(todo)
        if not complete:
            break
    return found_new


def _worker_done(future) -> None:
    global _worker_running
    with _pending_lock:
        _worker_running = False
    found_new = 0
    try:
        found_new = future.result() or 0
    except Exception as exc:
        print("[Flexikon] Hintergrundprüfung:", exc)
    with _pending_lock:
        more = bool(_pending)
    if more:
        _start_worker()
    if found_new:
        _refresh_current_card()


def _refresh_current_card() -> None:
    """
    Markiert die gerade sichtbare Karte erneut, nachdem die Prüfung neue
    Begriffe bestätigt hat. Ohne das würden sie erst beim nächsten Sehen
    der Karte erscheinen. Läuft im Hauptthread (Anki ruft die
    Fertig-Rückmeldung dort auf).
    """
    if not get_config().get("sofort_nachziehen", True):
        return
    try:
        if mw.state != "review" or not mw.reviewer or not mw.reviewer.card:
            return
        card = mw.reviewer.card
        side = getattr(mw.reviewer, "state", "question")
        if (
            _last_render.get("card_id") != card.id
            or _last_render.get("side") != side
        ):
            return  # inzwischen weitergeblättert
        text = card.answer() if side == "answer" else card.question()
        _highlight_text(text, requeue=False)
    except Exception as exc:
        print("[Flexikon] Nachziehen:", exc)


# ---------------------------------------------------------------- Markierung


def _is_card_view(context) -> bool:
    name = context.__class__.__name__ if context is not None else ""
    return name in (
        "Reviewer",
        "Previewer",
        "BrowserPreviewer",
        "SingleCardPreviewer",
        "MultiCardPreviewer",
        "CardLayout",
    )


def on_webview_will_set_content(web_content, context) -> None:
    if not _is_card_view(context):
        return
    pkg = addon_package()
    web_content.css.append("/_addons/%s/web/flexikon.css" % pkg)
    web_content.js.append("/_addons/%s/web/flexikon.js" % pkg)


def _highlight_text(text: str, requeue: bool = True) -> None:
    cfg = get_config()
    if not cfg.get("markierung_aktiv", True):
        return
    store = get_store()
    if store is None:
        return

    candidates = store_mod.extract_candidates(
        text,
        max_terms=int(cfg.get("max_begriffe_pro_karte", 60)),
        max_chain=int(cfg.get("max_wortkette", 3)),
    )
    found, unknown = store.resolve_terms(candidates)

    # Drei Sorten von Treffern:
    #   plain   – gewöhnliche Begriffe, Groß-/Kleinschreibung egal
    #   exact   – Abkürzungen, zeichengenau ("pH" soll nicht auf "ph" passen)
    #   aliases – Schreibweise auf der Karte → Artikel, der geöffnet wird
    #             ("M. biceps brachii" → "Musculus biceps brachii")
    plain, exact, aliases = [], [], {}
    for term, target in found.items():
        if target.lower() != term.lower():
            aliases[term] = target
        elif store_mod.is_abbreviation(term):
            exact.append(term)
        else:
            plain.append(term)

    opts = {
        "doubleClick": bool(cfg.get("doppelklick_nachschlagen", True)),
        "style": str(cfg.get("markierung_stil", "dotted")),
        "exact": exact,
        "aliases": aliases,
    }
    try:
        # Immer senden, auch ohne Treffer: die Seite merkt sich die
        # Anforderung und wendet sie an, sobald der Kartentext da ist.
        mw.reviewer.web.eval(
            "window.flexikonHighlight && flexikonHighlight(%s, %s);"
            % (
                json.dumps(plain, ensure_ascii=False),
                json.dumps(opts, ensure_ascii=False),
            )
        )
    except Exception as exc:
        print("[Flexikon] Markierung:", exc)

    if requeue:
        _queue_terms(unknown, front=True)


def _prefetch(text: str) -> None:
    """
    Stellt die Begriffe einer noch nicht gezeigten Seite hinten in die
    Warteschlange. Während die Frage gelesen wird, ist die Antwortseite
    so meist schon geprüft.
    """
    cfg = get_config()
    if not cfg.get("antwort_vorbereiten", True):
        return
    store = get_store()
    if store is None:
        return
    try:
        candidates = store_mod.extract_candidates(
            text,
            max_terms=int(cfg.get("max_begriffe_pro_karte", 60)),
            max_chain=int(cfg.get("max_wortkette", 3)),
        )
        _known, unknown = store.resolve_terms(candidates)
        _queue_terms(unknown, front=False)
    except Exception as exc:
        print("[Flexikon] Vorbereiten:", exc)


def on_show_question(card) -> None:
    try:
        _last_render["card_id"] = card.id
        _last_render["side"] = "question"
        _highlight_text(card.question())
        _prefetch(card.answer())
    except Exception as exc:
        print("[Flexikon] Frageseite:", exc)


def on_show_answer(card) -> None:
    try:
        _last_render["card_id"] = card.id
        _last_render["side"] = "answer"
        _highlight_text(card.answer())
    except Exception as exc:
        print("[Flexikon] Antwortseite:", exc)


# ---------------------------------------------------------------- Nachrichten


def on_js_message(handled, message: str, context):
    if isinstance(message, str) and message.startswith("flexikon-lookup:"):
        term = message[len("flexikon-lookup:"):].strip()
        if term:
            open_lookup(term)
        return (True, None)
    return handled


def open_lookup(term: str) -> None:
    from . import flexikon_ui

    flexikon_ui.ArticleDialog.open_term(term, parent=mw)


# ---------------------------------------------------------------- Menü


def _lookup_selection_or_ask() -> None:
    from . import flexikon_ui

    def with_selection(selection) -> None:
        text = (selection or "").strip()
        dlg = flexikon_ui.ArticleDialog(mw)
        flexikon_ui.ArticleDialog._instance = dlg
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        if text and 2 < len(text) < 80:
            dlg.load(text)
        else:
            dlg.search_box.setFocus()

    try:
        if mw.state == "review" and mw.reviewer and mw.reviewer.web:
            mw.reviewer.web.evalWithCallback(
                "window.getSelection ? String(window.getSelection()) : ''",
                with_selection,
            )
            return
    except Exception:
        pass
    with_selection("")


def _toggle_highlighting() -> None:
    cfg = get_config()
    cfg["markierung_aktiv"] = not cfg.get("markierung_aktiv", True)
    save_config(cfg)
    _action_toggle.setChecked(cfg["markierung_aktiv"])
    tooltip(
        "Begriffsmarkierung ist jetzt %s."
        % ("an" if cfg["markierung_aktiv"] else "aus")
    )
    if cfg["markierung_aktiv"]:
        try:
            if mw.state == "review" and mw.reviewer.card:
                mw.reviewer._redraw_current_card()
        except Exception:
            pass


def _clear_cache() -> None:
    from aqt.utils import askUser

    store = get_store()
    if store is None:
        return
    if not askUser(
        "Zwischengespeicherte Artikel und geprüfte Begriffe löschen?\n\n"
        "Die Markierung baut sich danach beim Lernen neu auf."
    ):
        return
    store.clear_all()
    tooltip("Flexikon-Zwischenspeicher geleert.")


def _forget_negatives() -> None:
    store = get_store()
    if store is None:
        return
    count = store.forget_negative_terms()
    tooltip("%d nicht gefundene Begriffe werden erneut geprüft." % count)


_action_toggle = None


def build_menu() -> None:
    global _action_toggle
    from . import flexikon_ui

    menu = QMenu("DocCheck &Flexikon", mw)

    act_lookup = QAction("Begriff &nachschlagen …", mw)
    act_lookup.setShortcut(QKeySequence("Ctrl+Shift+D"))
    act_lookup.triggered.connect(_lookup_selection_or_ask)
    menu.addAction(act_lookup)

    menu.addSeparator()

    _action_toggle = QAction("Begriffe auf Karten &markieren", mw)
    _action_toggle.setCheckable(True)
    _action_toggle.setChecked(bool(get_config().get("markierung_aktiv", True)))
    _action_toggle.triggered.connect(_toggle_highlighting)
    menu.addAction(_action_toggle)

    act_stats = QAction("&Index-Statistik …", mw)
    act_stats.triggered.connect(flexikon_ui.show_stats)
    menu.addAction(act_stats)

    menu.addSeparator()

    act_test = QAction("&Verbindung testen …", mw)
    act_test.triggered.connect(flexikon_ui.run_connection_test)
    menu.addAction(act_test)

    act_retry = QAction("Nicht gefundene Begriffe erneut prüfen", mw)
    act_retry.triggered.connect(_forget_negatives)
    menu.addAction(act_retry)

    act_clear = QAction("Zwischenspeicher &leeren …", mw)
    act_clear.triggered.connect(_clear_cache)
    menu.addAction(act_clear)

    mw.form.menuTools.addMenu(menu)


# ---------------------------------------------------------------- Start


def _setup() -> None:
    try:
        mw.addonManager.setWebExports(__name__, r"web/.*\.(css|js)")
    except Exception as exc:
        print("[Flexikon] setWebExports:", exc)

    api.set_min_interval(float(get_config().get("anfrage_abstand_sekunden", 0.6)))

    gui_hooks.webview_will_set_content.append(on_webview_will_set_content)
    gui_hooks.reviewer_did_show_question.append(on_show_question)
    gui_hooks.reviewer_did_show_answer.append(on_show_answer)
    gui_hooks.webview_did_receive_js_message.append(on_js_message)
    gui_hooks.main_window_did_init.append(build_menu)


if mw is not None:
    _setup()
