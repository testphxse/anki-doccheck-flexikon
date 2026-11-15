# DocCheck Flexikon für Anki (inoffiziell)

Unterstreicht medizinische Fachbegriffe auf deinen Anki-Karten und macht sie
anklickbar. Ein Klick öffnet den passenden Artikel aus dem DocCheck Flexikon in
einem kleinen Fenster, ohne die Lernsitzung zu verlassen. Die Artikel werden
live über die offizielle Flexikon-API geladen.

> Inoffizielles Community-Projekt. Steht in keiner Verbindung zu DocCheck oder AMBOSS.
> Entwickelt mit Hilfe von KI (Claude).

## Installation

1. In Anki: **Werkzeuge → Add-ons → Add-on-Datei installieren …**
2. Die Datei `DocCheck_Flexikon.ankiaddon` auswählen.
3. Anki neu starten.

Alternativ den Ordner `flexikon_lookup` direkt nach
`Werkzeuge → Add-ons → Add-on-Ordner öffnen` kopieren.

## Erste Schritte

Nach dem Neustart gibt es unter **Werkzeuge → DocCheck Flexikon**:

| Eintrag | Zweck |
|---|---|
| Begriff nachschlagen … (`Strg+Umschalt+D`) | Markierten Text nachschlagen, sonst Suchfeld öffnen |
| Begriffe auf Karten markieren | Markierung an-/abschalten |
| Index-Statistik … | Wie viele Begriffe bereits geprüft sind |
| Verbindung testen … | Prüft alle API-Endpunkte und zeigt das Ergebnis |
| Nicht gefundene Begriffe erneut prüfen | Negativtreffer verwerfen |
| Zwischenspeicher leeren … | Index und Artikel-Cache zurücksetzen |

**Starte mit „Verbindung testen …“.** Der Test zeigt im Klartext, ob die
Flexikon-API erreichbar ist und welcher Endpunkt gegebenenfalls klemmt.

## Wie die Markierung funktioniert

Der Begriffsindex baut sich **beim Lernen von selbst auf**:

1. Beim Anzeigen einer Karte zieht das Addon Kandidaten aus dem Kartentext.
2. Bereits bekannte Begriffe werden sofort markiert – offline, ohne Anfrage.
3. Unbekannte Begriffe werden im Hintergrund geprüft und das Ergebnis
   dauerhaft gespeichert. Dank Sammelabfrage reichen dafür ein bis drei
   Anfragen pro neuer Karte: eine für die Begriffe, wie sie dastehen, und
   bei Bedarf weitere für Vollformen und Grundformen (siehe unten).
4. Sobald die Antwort da ist, wird die **noch sichtbare Karte sofort
   nachgezogen** – die Begriffe erscheinen also schon beim ersten Sehen,
   nicht erst beim nächsten Durchgang.

Während du die Frage liest, wird die Antwortseite im selben Stapel
mitgeprüft. Beim Umdrehen ist die Markierung deshalb meist sofort da.

Die ersten Sitzungen markieren etwas weniger, danach wird es schnell dichter.
Es wird **kein** Massen-Download der Flexikon-Begriffe gemacht.

### Wortketten

Erkannt werden nicht nur einzelne Wörter, sondern Ketten bis zu vier Gliedern
(`max_wortkette`, Standard 3):

| Beispiel | Glieder |
|---|---|
| Zona pellucida, Corpus luteum, Morbus Crohn | 2 |
| Corpus luteum gravidarum, Ampulla tubae uterinae | 3 |
| Arteria carotis communis dextra | 4 |

Damit aus Fließtext kein Unsinn wird, enden Ketten an Satzzeichen, Pfeilen
(`→`), Zeilen- und Absatzgrenzen, Stoppwörtern und Verbformen. Ein
kleingeschriebenes Folgeglied muss zudem lateinisch wirken – aus
„Granulosazellen bilden Progesteron“ entsteht deshalb keine Kette, aus
„Zona pellucida“ schon. Großgeschriebene Folgeglieder sind immer erlaubt,
damit „Morbus Crohn“ oder „Kleines Becken“ greifen.

Eine Kette wird auch dann erkannt, wenn sie **über Formatierungsgrenzen**
läuft: `<b>Corpus</b> luteum gravidarum` wird als ein Begriff markiert.
Über Absatz-, Zeilen- und Tabellengrenzen hinweg wird dagegen bewusst nicht
verbunden. Steht ein längerer und ein kürzerer Begriff zur Auswahl, gewinnt
der längere.

### Anatomische Kurzformen

Auf der Karte steht `M. biceps brachii`, der Artikel im Flexikon heißt
`Musculus biceps brachii`. Das Addon merkt sich diesen Zusammenhang:
**markiert wird die Schreibweise der Karte, geöffnet wird der Artikel.**

| Auf der Karte | Geöffnet wird |
|---|---|
| `M. biceps brachii` | Musculus biceps brachii |
| `Lig. cruciatum anterius` | Ligamentum cruciatum anterius |
| `Proc accessorius` (ohne Punkt) | Processus accessorius |
| `Mm. intercostales externi` | Musculi intercostales externi – oder, wenn es nur die Einzahl gibt, Musculus intercostalis externus |

Erkannt werden, Singular wie Plural:

| | | | |
|---|---|---|---|
| `M.` / `Mm.` Musculus | `A.` / `Aa.` Arteria | `V.` / `Vv.` Vena | `N.` / `Nn.` Nervus |
| `Lig.` / `Ligg.` Ligamentum | `Art.` / `Artt.` Articulatio | `R.` / `Rr.` Ramus | `Gl.` / `Gll.` Glandula |
| `Proc.` Processus | `Nucl.` Nucleus | `For.` Foramen | `Tub.` Tuberculum |
| `Tr.` Tractus | `Trunc.` Truncus | `Sin.` Sinus | `Fasc.` Fasciculus |
| `Lam.` Lamina | `Lob.` Lobus | `Can.` Canalis | `Vag.` Vagina |
| `Vent.` Ventriculus | `Seg.` Segmentum | `Pl.` Plexus | `Ggl.` Ganglion |

Ohne Punkt zählt eine Kurzform erst ab drei Buchstaben (`Proc`, `Lig`,
`Artt`) und nur, wenn ein lateinisch wirkendes Wort folgt – ein einzelnes
„A“ oder „M“ ohne Punkt kann alles Mögliche sein.

Alltagskürzel lösen das nicht aus: `u. a. durch`, `i. v. mittels` und
`V. a. Appendizitis` bleiben unberührt. Auch ein angehängtes Verb wird
abgeschnitten – aus „M. biceps brachii beugt“ wird „M. biceps brachii“.

Ausgeschriebene Formen funktionieren ebenso: nach einem lateinischen
Kopfwort (Musculus, Arteria, Nervus, Os, Ligamentum, Processus …) darf das
Folgewort beliebig aussehen, sonst fiele „Musculus **biceps**“ durch.

### Gebeugte Formen

Dasselbe gilt für Mehrzahl und Fälle: „Oozyten“ führt zu „Oozyte“,
„Hormone“ zu „Hormon“, „Keimblätter“ zu „Keimblatt“, „Spermien“ zu
„Spermium“. Die Grundformen sind Vermutungen des Addons; verwendet wird eine
nur, wenn es den Artikel im Flexikon wirklich gibt.

Beides lässt sich mit `grundform_versuchen: false` abschalten. Dann zählt
nur noch, was wörtlich als Titel existiert.

### Abkürzungen

Erkannt werden auch medizinische Kürzel – FSME, FSH, LH, ZNS, hCG, mRNA,
pH, T3, T4, IL-6, CD4, HbA1c, IgG, GnRH. Mitgenommen werden dabei:

- reine Großbuchstaben ab zwei Zeichen (`LH`, `ZNS`, `COPD`)
- gemischte Schreibweisen (`hCG`, `mRNA`, `pH`, `IgG`)
- Kürzel mit Ziffern (`T3`, `CD4`, `IL-6`, `HbA1c`)
- zusammengesetzte Formen (`pH-Wert`, `mRNA-Expression`) – zusätzlich wird
  das Kürzel selbst angeboten
- Kürzel in Ketten (`Vitamin B12`, `Faktor VIII`)

Abkürzungen werden **zeichengenau** gesucht. `hCG` trifft also nicht auf
`hcg`, und `T3` nicht innerhalb von `T34`. Gewöhnliche Wörter und Wortketten
bleiben dagegen unabhängig von Groß- und Kleinschreibung.

Zusammensetzungen aus normalen Wörtern gelten nicht als Abkürzung:
`Hensen-Knoten` und `Vater-Pacini-Körperchen` bleiben gewöhnliche Begriffe.
In Lernkarten großgeschriebene Hervorhebungen (`EIN`, `MERKE`, `WICHTIG`)
werden herausgefiltert.

> **Zur Vorsicht:** Kurze Kürzel sind oft mehrdeutig. Steht `RT` auf deiner
> Karte für „Reifeteilung“, kann das Flexikon darunter etwas anderes führen.
> Das Popup zeigt Titel und Fachgebiete, sodass eine Verwechslung sofort
> auffällt.

## Bedienung während des Lernens

- **Klick** auf einen markierten Begriff → Artikel im Popup
- **Doppelklick** auf ein beliebiges Wort → Artikel im Popup

### Im Popup

| Bedienung | Wirkung |
|---|---|
| Eingabetaste im Suchfeld | schlägt **im Fenster** nach |
| „Aktualisieren“ | dasselbe per Knopf |
| „Im Browser öffnen“ | öffnet den Artikel im Webbrowser |
| `Strg`+Eingabetaste | wie „Im Browser öffnen“ |
| `◀` | zurück zum vorigen Artikel |
| `Strg`+`F` | Suchfeld fokussieren und Text markieren |
| `Esc` | schließt |

Die Eingabetaste bleibt also immer im Fenster; in den Browser geht es nur
über den Knopf. Links im Artikel führen ebenfalls im Fenster weiter.

### Wenn kein Artikel gefunden wird

Gibt es zum Begriff keinen Artikel, versucht das Fenster dieselben
Vollformen und Grundformen wie die Markierung („Proc accessorius“ →
„Processus accessorius“, „Oozyten“ → „Oozyte“) und zeigt den gefundenen
Artikel mit einem Hinweis an. Bei Wortketten kommt als letzte Möglichkeit
das erste Wort allein dazu („Corpus lutei“ → „Corpus“).

Hilft das nicht – etwa bei „Progesteronspiegel“, wo der gesuchte Teil vorn
steht –, bleibt der Begriff im Suchfeld stehen und ist bereits markiert:
kürzen und Eingabetaste drücken. Liefert die Volltextsuche des Flexikons
Treffer, erscheinen sie als Vorschläge. Geratene Formen, die es nicht gibt,
werden nie angezeigt.

## Einstellungen

**Werkzeuge → Add-ons → Add-on auswählen → Einstellungen.**
Die Bedeutung aller Schlüssel steht in `config.md`.

Stile für `markierung_stil`: `dotted`, `underline`, `color`, `subtle`.

Einzelne Bereiche einer Karte lassen sich von der Markierung ausnehmen, indem
du sie im Kartentemplate in `<span class="flexikon-skip"> … </span>` setzt.

## Technisches

- Genutzte Endpunkte: die unter `flexikon.doccheck.com/llms.txt` dokumentierten
  (`api.php?action=parse`, Portalsuche, `rest.php/.../categories`).
- Zusätzlich `api.php?action=query` für die Sammelabfrage – der
  MediaWiki-Standard, in der Kurzdoku nicht aufgeführt. Er ersetzt bis zu 50
  Einzelabrufe durch einen und entlastet die Server dadurch erheblich. Ist er
  nicht verfügbar, schaltet das Addon automatisch auf die dokumentierte
  Einzelprüfung um; `sammelabfrage: false` erzwingt das.
- Anfragen tragen einen aussagekräftigen User-Agent und sind ratenbegrenzt,
  wie es die Doku erbittet.
- Index und Artikel-Cache liegen in `user_files/flexikon.db` und überleben
  Addon-Updates.
- Keine externen Python-Abhängigkeiten, nur die Standardbibliothek.
- Lauffähig ab Anki 2.1.50 (`min_point_version: 50`). Wirklich geprüft
  wurde in einer echten Anki-Instanz der Version 26.09, im hellen und im
  dunklen Design. Ältere Versionen sind nicht getestet.
- Nicht live getestet sind die Antworten des Flexikons selbst: die
  Entwicklungsumgebung erreicht doccheck.com nicht, geprüft wurde gegen ein
  nachgebautes MediaWiki. „Verbindung testen …“ zeigt, ob es bei dir passt.

## Rechtliches

- Das Addon enthält **keine** Flexikon-Inhalte. Artikel werden erst beim
  Nachschlagen live über die öffentlich dokumentierte API
  (`flexikon.doccheck.com/llms.txt`) geladen, mit eigenem User-Agent und
  begrenzter Anfragerate.
- Die Texte des Flexikons stehen laut den
  [Flexikon-Nutzungsbedingungen](https://flexikon.doccheck.com/de/Flexikon:Nutzungsbedingungen)
  unter **CC BY-NC-SA 4.0**. Bilder sind davon ausgenommen und gehören DocCheck
  bzw. den Bildautoren. Jedes Popup nennt DocCheck Flexikon als Quelle und
  verlinkt den Originalartikel („Im Browser öffnen“).
- Gedacht ausschließlich für den persönlichen, nicht-kommerziellen Lerngebrauch.
  Es wird kein Bulk-Download gemacht; der Artikel-Cache ist zeitlich begrenzt
  (`artikel_cache_stunden`).
- „DocCheck“ ist ein Name bzw. eine Marke der DocCheck-Gruppe. Dieses Addon steht
  in keiner Verbindung zu DocCheck oder AMBOSS. Bei Einwänden von DocCheck
  bitte ein Issue öffnen – das Repository wird dann angepasst oder entfernt.
