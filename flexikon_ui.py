# -*- coding: utf-8 -*-
"""Popup-Fenster und Dialoge für das Flexikon-Addon."""

from __future__ import annotations

import html as html_mod

from aqt import mw
from aqt.operations import QueryOp
from aqt.qt import (
    QDialog,
    QHBoxLayout,
    QKeySequence,
    QLabel,
    QLineEdit,
    QPushButton,
    QShortcut,
    QSize,
    Qt,
    QVBoxLayout,
)
from aqt.utils import openLink, restoreGeom, saveGeom, showWarning, tooltip
from aqt.webview import AnkiWebView

from . import flexikon_api as api

GEOM_KEY = "flexikonLookupDialog"

# Farben kommen aus Ankis eigenen Variablen (--fg, --fg-link …). Dadurch
# passt das Fenster von selbst zum hellen wie zum dunklen Design – und zwar
# zu dem, das in Anki eingestellt ist, nicht zu dem des Betriebssystems.
_POPUP_CSS = """
body { font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
       font-size: 15px; line-height: 1.55; margin: 0; padding: 18px 22px 30px; }
.fx-title { font-size: 22px; font-weight: 600; line-height: 1.25; margin: 0 0 4px; }
.fx-cats { font-size: 12px; color: var(--fg-subtle, #737373); margin-bottom: 14px; }
.fx-body img { max-width: 100%; height: auto; }
.fx-body table { border-collapse: collapse; max-width: 100%; }
.fx-body td, .fx-body th { border: 1px solid rgba(128,128,128,.4); padding: 4px 7px; }
.fx-body h2 { font-size: 18px; margin: 22px 0 6px; padding-bottom: 3px;
              border-bottom: 1px solid rgba(128,128,128,.3); }
.fx-body h3 { font-size: 16px; margin: 16px 0 4px; }
.fx-body a, .fx-chip { color: var(--fg-link, #1d4ed8); text-decoration: none; }
.fx-body a:hover { text-decoration: underline; }
.fx-note { margin-top: 26px; padding-top: 10px; font-size: 12px;
           border-top: 1px solid rgba(128,128,128,.3); color: var(--fg-subtle, #737373); }
.fx-msg { padding: 20px 0 8px; }
.fx-msg-title { font-size: 19px; font-weight: 600; line-height: 1.3; margin: 0 0 8px; }
.fx-msg-text { margin: 0; max-width: 60ch; opacity: .8; }
.fx-sugg { margin-top: 22px; }
.fx-sugg-label { font-size: 11px; letter-spacing: .07em; text-transform: uppercase;
                 color: var(--fg-subtle, #737373); margin-bottom: 8px; }
.fx-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.fx-chip { display: inline-block; padding: 4px 13px; border-radius: 999px;
           border: 1px solid rgba(128,128,128,.5); font-size: 13px; line-height: 1.5; }
.fx-chip:hover { background: rgba(128,128,128,.18); }
.fx-hint { margin: 0 0 14px; padding: 7px 11px; font-size: 13px; border-radius: 3px;
           border-left: 3px solid #d99a06; background: rgba(217,154,6,.14); }
"""


class ArticleDialog(QDialog):
    """Zeigt einen Flexikon-Artikel. Interne Links werden im Fenster geöffnet."""

    _instance = None

    def __init__(self, parent=None) -> None:
        QDialog.__init__(self, parent or mw)
        self.setWindowTitle("DocCheck Flexikon")
        self.setMinimumSize(QSize(560, 420))
        self._history = []
        self._current = None
        self._current_url = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        bar = QHBoxLayout()
        self.back_btn = QPushButton("◀")
        self.back_btn.setFixedWidth(36)
        self.back_btn.setToolTip("Zurück")
        self.back_btn.clicked.connect(self._go_back)
        self.back_btn.setEnabled(False)
        bar.addWidget(self.back_btn)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText(
            "Begriff ändern und Eingabetaste drücken …"
        )
        self.search_box.setClearButtonEnabled(True)
        self.search_box.returnPressed.connect(self._on_search_entered)
        bar.addWidget(self.search_box, 1)

        self.refresh_btn = QPushButton("Aktualisieren")
        self.refresh_btn.setToolTip(
            "Begriff hier im Fenster nachschlagen (Eingabetaste)"
        )
        self.refresh_btn.clicked.connect(self._on_search_entered)
        bar.addWidget(self.refresh_btn)

        self.browser_btn = QPushButton("Im Browser öffnen")
        self.browser_btn.setToolTip(
            "Artikel im Webbrowser öffnen (Strg+Eingabetaste)"
        )
        self.browser_btn.clicked.connect(self._open_in_browser)
        bar.addWidget(self.browser_btn)
        layout.addLayout(bar)

        # Ein QPushButton in einem QDialog ist von sich aus der Standardknopf,
        # den die Eingabetaste mit auslöst. Ohne das Abschalten würde Enter im
        # Suchfeld zusätzlich den Browser aufmachen.
        for button in (self.back_btn, self.refresh_btn, self.browser_btn):
            button.setAutoDefault(False)
            button.setDefault(False)

        self.web = AnkiWebView(parent=self, title="flexikon")
        self.web.set_bridge_command(self._on_bridge, self)
        layout.addWidget(self.web, 1)

        self.status = QLabel("")
        self.status.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(self.status)

        QShortcut(QKeySequence("Esc"), self, activated=self.close)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self._focus_search)
        QShortcut(
            QKeySequence("Ctrl+Return"), self, activated=self._open_in_browser
        )
        QShortcut(
            QKeySequence("Ctrl+Enter"), self, activated=self._open_in_browser
        )
        restoreGeom(self, GEOM_KEY)

    def _focus_search(self) -> None:
        self.search_box.setFocus()
        self.search_box.selectAll()

    # -------------------------------------------------- Klassenzugriff

    @classmethod
    def open_term(cls, term: str, parent=None) -> "ArticleDialog":
        dlg = cls._instance
        if dlg is None or not _alive(dlg):
            dlg = cls(parent)
            cls._instance = dlg
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        dlg.load(term)
        return dlg

    # -------------------------------------------------- Laden

    def load(self, term: str, push_history: bool = True) -> None:
        term = " ".join((term or "").split())
        if not term:
            return
        if push_history and self._current and self._current != term:
            self._history.append(self._current)
            self.back_btn.setEnabled(True)
        self._current = term
        self.search_box.setText(term)
        self.setWindowTitle("DocCheck Flexikon – %s" % term)
        self._render_message(
            "Lade …", "„%s“ wird vom Flexikon geholt." % html_mod.escape(term)
        )
        self.status.setText("Lade …")

        config = mw.addonManager.getConfig(_pkg()) or {}
        max_age = float(config.get("artikel_cache_stunden", 72)) * 3600
        try_forms = bool(config.get("grundform_versuchen", True))
        store = _store()

        def fetch(title: str) -> dict:
            cached = store.get_article(title, max_age) if store else None
            if cached:
                cached["_cached"] = True
                return cached
            art = api.fetch_article(title)
            try:
                art["categories"] = api.fetch_categories(art["raw_title"])
            except Exception:
                art["categories"] = []
            if store:
                store.put_article(title, art)
            return art

        def op(_col):
            try:
                art = fetch(term)
                if store:
                    store.record_term(term, True)
                return {"ok": True, "data": art}
            except api.ArticleMissing:
                pass
            except api.FlexikonError as exc:
                return {"ok": False, "missing": False, "error": str(exc)}

            # Kein Artikel unter diesem Titel. Kurzformen werden
            # ausgeschrieben ("Proc accessorius" → "Processus accessorius"),
            # gebeugte Formen auf die Grundform gebracht ("Oozyten" →
            # "Oozyte"). Verwendet wird nur, was es im Flexikon gibt.
            forms = api.title_variants(term) if try_forms else []
            hit = _first_existing(forms, store)
            if hit:
                try:
                    art = dict(fetch(hit))
                    art["_variant_of"] = term
                    if store and hit in api.title_variants(term, head_fallback=False):
                        # Merken, damit die Schreibweise der Karte künftig
                        # markiert wird und direkt zum Artikel führt.
                        store.record_term(term, True, hit)
                    return {"ok": True, "data": art}
                except api.FlexikonError:
                    pass
            return {"ok": False, "missing": True, "suggestions": _safe_search(term)}

        QueryOp(parent=self, op=op, success=self._on_loaded).run_in_background()

    def _on_loaded(self, result: dict) -> None:
        if not _alive(self):
            return
        if result.get("ok"):
            self._show_article(result["data"])
            _refresh_card_marks()
            return
        if result.get("missing"):
            self._current_url = api.article_url(self._current or "")
            self._render_missing(
                self._current or "", result.get("suggestions") or []
            )
            self.status.setText(
                "Kein Artikel gefunden. Begriff oben ändern und Eingabetaste "
                "drücken."
            )
            self._focus_search()
        else:
            self._current_url = ""
            self._render_message(
                "Abruf fehlgeschlagen", html_mod.escape(result.get("error", ""))
            )
            self.status.setText("Fehler beim Abruf.")

    def _show_article(self, art: dict) -> None:
        self._current_url = art.get("url", "")
        body = api.clean_article_html(art.get("html", ""))
        cats = art.get("categories") or []
        cats_html = ""
        if cats:
            cats_html = '<div class="fx-cats">%s</div>' % html_mod.escape(
                " · ".join(cats[:8])
            )
        variant_of = art.get("_variant_of")
        hint = ""
        if variant_of:
            hint = (
                '<div class="fx-hint">Zu „%s“ gibt es keinen Eintrag – '
                "angezeigt wird „%s“.</div>"
                % (
                    html_mod.escape(variant_of),
                    html_mod.escape(art.get("title", "")),
                )
            )
        page = (
            '<h1 class="fx-title">%s</h1>%s%s<div class="fx-body">%s</div>'
            '<div class="fx-note">Quelle: DocCheck Flexikon – %s<br>'
            "Inhalt wird live abgerufen und gehört DocCheck. Nur für den "
            "persönlichen Lerngebrauch.</div>"
            % (
                html_mod.escape(art.get("title", "")),
                cats_html,
                hint,
                body,
                html_mod.escape(art.get("url", "")),
            )
        )
        self._render(page)
        self.web.eval("document.documentElement.scrollTop=0;")
        title = art.get("title", "")
        self.setWindowTitle("DocCheck Flexikon – %s" % title)
        if title:
            # Das Feld zeigt den gefundenen Titel, damit „Im Browser öffnen“
            # und eine weitere Änderung von dort aus weitergehen.
            self.search_box.setText(title)
            self._current = title
        if variant_of:
            self.status.setText("Angezeigt wird „%s“." % title)
        else:
            self.status.setText(
                "Aus dem Zwischenspeicher." if art.get("_cached") else "Geladen."
            )

    @staticmethod
    def _link_list(label: str, titles: list) -> str:
        """Vorschläge als antippbare Pillen statt als Linkliste."""
        if not titles:
            return ""
        chips = "".join(
            '<a class="fx-chip" href="#" '
            "onclick=\"pycmd('flexikon-nav:%s'); return false;\">%s</a>"
            % (
                title.replace("\\", "\\\\").replace("'", "\\'"),
                html_mod.escape(title),
            )
            for title in titles
        )
        return (
            '<div class="fx-sugg"><div class="fx-sugg-label">%s</div>'
            '<div class="fx-chips">%s</div></div>'
            % (html_mod.escape(label), chips)
        )

    def _render_missing(self, term: str, suggestions: list) -> None:
        # Vorschläge stammen aus der Volltextsuche des Flexikons, es gibt
        # sie also wirklich. Geratene Grundformen werden nie angezeigt.
        blocks = self._link_list(
            "Volltextsuche", [s["title"] for s in suggestions[:8]]
        )
        self._render_message(
            "Kein Artikel „%s“" % html_mod.escape(term),
            "Das Flexikon hat unter diesem Titel keinen Eintrag. Ändere den "
            "Begriff oben im Feld und drücke die Eingabetaste.",
            extra=blocks,
        )

    def _render_message(self, title: str, text: str, extra: str = "") -> None:
        self._render(
            '<div class="fx-msg"><div class="fx-msg-title">%s</div>'
            '<div class="fx-msg-text">%s</div>%s</div>' % (title, text, extra)
        )

    def _render(self, body: str) -> None:
        # Die Gestaltung muss über `head` mitgegeben werden. `css=` nimmt nur
        # Dateinamen aus Ankis eigenem Bestand an; ohne `head` käme die
        # Seite völlig ungestaltet an.
        self.web.stdHtml(
            body,
            css=[],
            js=[],
            head="<style>%s</style>" % _POPUP_CSS,
            context=self,
        )

    # -------------------------------------------------- Interaktion

    def _on_bridge(self, cmd: str) -> object:
        if cmd.startswith("flexikon-nav:"):
            self.load(cmd[len("flexikon-nav:"):])
            return True
        if cmd.startswith("flexikon-ext:"):
            openLink(cmd[len("flexikon-ext:"):])
            return True
        return False

    def _on_search_entered(self) -> None:
        self.load(self.search_box.text())

    def _go_back(self) -> None:
        if not self._history:
            return
        previous = self._history.pop()
        self.back_btn.setEnabled(bool(self._history))
        self.load(previous, push_history=False)

    def _open_in_browser(self) -> None:
        url = self._current_url or api.article_url(self._current or "")
        if url:
            openLink(url)

    # -------------------------------------------------- Qt

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt-Signatur
        saveGeom(self, GEOM_KEY)
        try:
            self.web.cleanup()
        except Exception:
            pass
        ArticleDialog._instance = None
        QDialog.closeEvent(self, event)

    def reject(self) -> None:
        self.close()


# ------------------------------------------------------------------ Helfer


def _alive(widget) -> bool:
    try:
        widget.isVisible()
        return True
    except RuntimeError:
        return False


def _pkg() -> str:
    return mw.addonManager.addonFromModule(__name__)


def _store():
    from . import get_store

    return get_store()


def _first_existing(titles: list, store) -> "str | None":
    """
    Der erste Titel der Liste, den es im Flexikon gibt – oder None.
    Nutzt zuerst den lokalen Index, dann eine Sammelanfrage; ist die nicht
    verfügbar, werden die besten drei einzeln probiert.
    """
    if not titles:
        return None
    if store:
        known, _unknown = store.resolve_terms(titles)
        for title in titles:
            if title in known:
                return known[title]
    try:
        present = api.article_exists_many(titles)
    except api.FlexikonError:
        present = {}
        for title in titles[:3]:
            try:
                present[title] = api.article_exists(title)
            except api.FlexikonError:
                break
            if present[title]:
                break
    for title in titles:
        if present.get(title):
            return title
    return None


def _refresh_card_marks() -> None:
    """Zieht die Marken der sichtbaren Karte nach, falls das Nachschlagen
    dem Index etwas Neues beigebracht hat."""
    try:
        from . import _refresh_current_card

        _refresh_current_card()
    except Exception:
        pass


def _safe_search(term: str) -> list:
    try:
        return api.search(term, limit=8)
    except Exception:
        return []


# ------------------------------------------------------------------ Diagnose


def run_connection_test() -> None:
    """Prüft alle genutzten Endpunkte und zeigt das Ergebnis im Klartext."""

    def op(_col):
        lines = []
        ok_any = False
        try:
            art = api.fetch_article("Herz")
            lines.append(
                "✔ Artikel-API: „%s“ geladen (%d Zeichen HTML)"
                % (art["title"], len(art["html"]))
            )
            ok_any = True
        except Exception as exc:
            lines.append("✘ Artikel-API fehlgeschlagen: %s" % exc)
        try:
            exists = api.article_exists("Insulin")
            lines.append(
                "✔ Existenzprüfung: „Insulin“ → %s"
                % ("vorhanden" if exists else "nicht vorhanden")
            )
            ok_any = True
        except Exception as exc:
            lines.append("✘ Existenzprüfung fehlgeschlagen: %s" % exc)
        try:
            hits = api.search("Herz", limit=5)
            if hits:
                lines.append(
                    "✔ Suche: %d Treffer, erster: „%s“" % (len(hits), hits[0]["title"])
                )
            else:
                lines.append(
                    "✘ Suche lieferte keine auswertbaren Treffer. "
                    "Das Antwortformat der Portalsuche ist nicht dokumentiert – "
                    "Nachschlagen und Markieren funktionieren trotzdem, nur die "
                    "Vorschläge bei Tippfehlern fallen weg."
                )
        except Exception as exc:
            lines.append("✘ Suche fehlgeschlagen: %s" % exc)
        try:
            cats = api.fetch_categories("Herz")
            lines.append(
                "✔ Kategorien: %s" % (", ".join(cats[:5]) if cats else "(keine)")
            )
        except Exception as exc:
            lines.append("✘ Kategorien fehlgeschlagen: %s" % exc)
        return {"lines": lines, "ok": ok_any}

    def done(result: dict) -> None:
        from aqt.utils import showText

        header = (
            "Verbindung zum DocCheck Flexikon\n"
            "User-Agent: %s\n\n" % api.USER_AGENT
        )
        showText(header + "\n".join(result["lines"]), title="Flexikon – Verbindungstest")
        if not result["ok"]:
            tooltip("Keine Verbindung zum Flexikon.")

    QueryOp(parent=mw, op=op, success=done).with_progress(
        "Teste Verbindung zum Flexikon …"
    ).run_in_background()


def show_stats() -> None:
    from aqt.utils import showText

    store = _store()
    if not store:
        showWarning("Der lokale Index ist nicht verfügbar.")
        return
    st = store.stats()
    showText(
        "Lokaler Begriffsindex\n\n"
        "geprüfte Begriffe:            %d\n"
        "davon im Flexikon:            %d\n"
        "  über Kurz-/Grundform:       %d\n"
        "zwischengespeicherte Artikel: %d\n\n"
        "Der Index baut sich beim Lernen von selbst auf. Je mehr du lernst, "
        "desto mehr Begriffe werden markiert."
        % (st["geprueft"], st["vorhanden"], st["verweise"], st["artikel_cache"]),
        title="Flexikon – Index",
    )
