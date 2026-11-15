## DocCheck Flexikon – Einstellungen

**markierung_aktiv**
Begriffe auf den Karten markieren. `false` schaltet die Markierung ab; das
Nachschlagen über Menü, Doppelklick und `Strg+Umschalt+D` bleibt möglich.

**markierung_stil**
Aussehen der markierten Begriffe:
`"dotted"` (gepunktete Linie, Standard), `"underline"` (durchgezogen),
`"color"` (nur eingefärbt), `"subtle"` (zarter Hintergrund).

**doppelklick_nachschlagen**
Doppelklick auf ein beliebiges Wort der Karte schlägt es nach – auch dann,
wenn es nicht markiert ist.

**hintergrund_pruefung**
Unbekannte Begriffe der gelernten Karte im Hintergrund einmal gegen das
Flexikon prüfen. So baut sich der Index beim Lernen von selbst auf.
`false` lässt den Index unverändert; markiert wird dann nur, was schon
bekannt ist.

**max_wortkette**
Aus wie vielen Wörtern ein Begriff höchstens bestehen darf.
`1` = nur Einzelwörter, `2` = auch „Corpus luteum“, `3` (Standard) = auch
„Corpus luteum gravidarum“, `4` = auch „Arteria carotis communis dextra“.
Höhere Werte finden mehr, erzeugen aber mehr Kandidaten zum Prüfen.

Ketten enden automatisch an Satzzeichen, Stoppwörtern und Verbformen. Aus
„Granulosazellen bilden Progesteron“ wird deshalb kein Kandidat
„Granulosazellen bilden“.

Medizinische Abkürzungen (FSME, FSH, hCG, pH, T3, IL-6 …) werden unabhängig
von dieser Einstellung immer erkannt und zeichengenau gesucht.

**max_begriffe_pro_karte**
Wie viele Kandidaten pro Karte überhaupt betrachtet werden. Bereits bekannte
Begriffe kosten nichts – der Wert darf großzügig sein.

**max_pruefungen_pro_karte**
Wie viele noch unbekannte Begriffe pro Karte höchstens neu angefragt werden.

**sammelabfrage**
Prüft bis zu 50 Begriffe mit einer einzigen Anfrage statt mit 50 einzelnen.
Das entlastet die DocCheck-Server deutlich und macht lange Wortketten erst
bezahlbar. Nutzt `action=query`, den MediaWiki-Standard; sollte der nicht
verfügbar sein, schaltet das Addon von selbst auf Einzelprüfung um.
`false` erzwingt die Einzelprüfung.

**sofort_nachziehen**
Sobald die Hintergrundprüfung neue Begriffe bestätigt hat, wird die gerade
sichtbare Karte erneut markiert. Ohne das erschienen die Begriffe erst beim
nächsten Sehen der Karte. Nachgezogen wird nur, wenn dieselbe Karte und
dieselbe Seite noch auf dem Bildschirm steht.

**antwort_vorbereiten**
Während du die Frage liest, werden die Begriffe der Antwortseite schon
geprüft. Beim Umdrehen ist die Markierung dadurch meist sofort da. Kostet
keine zusätzliche Anfrage, weil beide Seiten im selben Stapel landen.

**grundform_versuchen**
Gibt es einen Begriff nicht wörtlich als Artikel, werden die Vollform und
die Grundform probiert: „M. biceps brachii“ → „Musculus biceps brachii“,
„Mm. intercostales externi“ → „Musculus intercostalis externus“,
„Oozyten“ → „Oozyte“, „Keimblätter“ → „Keimblatt“. Das gilt für die
Markierung auf der Karte ebenso wie für das Nachschlagefenster. Markiert
wird die Schreibweise der Karte, geöffnet der gefundene Artikel.

Kostet beim ersten Sehen einer Karte ein bis zwei zusätzliche Anfragen,
weil alle Formen gemeinsam geprüft werden. Ohne Sammelabfrage werden nur
Kurzformen ausgeschrieben; Endungen werden dann nicht probiert, weil jede
Form eine eigene Anfrage kosten würde.

`false`: nur wörtliche Titel zählen.

**anfrage_abstand_sekunden**
Mindestabstand zwischen zwei Anfragen. Nicht unter 0,3 setzen.

**artikel_cache_stunden**
Wie lange ein geladener Artikel lokal wiederverwendet wird, bevor er neu
geholt wird. `0` schaltet den Artikel-Zwischenspeicher ab.

---

Die Inhalte stammen vom DocCheck Flexikon und werden nur auf Abruf für den
persönlichen Lerngebrauch geladen. Die Rechte daran liegen bei DocCheck.
