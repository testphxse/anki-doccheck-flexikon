/* DocCheck-Flexikon-Addon: markiert Fachbegriffe auf der Karte.
 *
 * Treffer werden über zusammenhängende Textabschnitte gesucht, nicht je
 * Textknoten. Dadurch wird auch "<b>Corpus</b> luteum" erkannt; die Marke
 * verteilt sich dann auf mehrere Elemente, trägt aber überall den vollen
 * Begriff. Blockgrenzen (Absatz, Zeilenumbruch, Tabellenzelle, Listenpunkt)
 * trennen die Abschnitte, damit keine Treffer über Satzgrenzen entstehen.
 *
 * Zwei Dinge sind für die Zuverlässigkeit entscheidend:
 *
 * 1. Jede Markierung beginnt auf sauberem Text. Alte Marken werden vorher
 *    entfernt, damit ein später bestätigter längerer Begriff ("Corpus
 *    luteum") eine schon gesetzte kurze Marke ("Corpus") ersetzen kann.
 *
 * 2. Anki baut die Karte zeitversetzt auf – bei Karten mit Bildern erst,
 *    wenn die Bilder geladen sind. Die Markierungsanforderung kann deshalb
 *    VOR dem Kartentext eintreffen. Sie wird gemerkt und erneut angewendet,
 *    sobald sich der Karteninhalt ändert.
 */
(function () {
  if (window.__flexikonReady) return;
  window.__flexikonReady = true;

  // Ziffern gehören zur Wortgrenze, damit "T3" nicht in "T34" trifft.
  var LETTER = "A-Za-z0-9\\u00C0-\\u024F";
  var options = { doubleClick: true, style: "dotted" };

  var request = null;      // zuletzt angeforderte Markierung, vorbereitet
  var observer = null;
  var timer = null;
  var lastText = null;     // Kartentext nach der letzten Markierung
  var lastCount = -1;      // Zahl der Marken nach der letzten Markierung
  var reapplies = 0;       // Schutz gegen Pingpong mit anderen Skripten
  var MAX_REAPPLIES = 25;

  var SKIP_TAGS = {
    SCRIPT: 1, STYLE: 1, TEXTAREA: 1, INPUT: 1, SELECT: 1, BUTTON: 1,
    CODE: 1, PRE: 1, KBD: 1, SAMP: 1, A: 1, svg: 1, SVG: 1,
    // Formeln nicht anfassen, sonst zerbricht der Formelsatz.
    "MJX-CONTAINER": 1, "ANKI-MATHJAX": 1, MATH: 1
  };

  var BLOCK_TAGS = {
    DIV: 1, P: 1, LI: 1, UL: 1, OL: 1, DL: 1, DT: 1, DD: 1, TABLE: 1,
    THEAD: 1, TBODY: 1, TFOOT: 1, TR: 1, TD: 1, TH: 1, H1: 1, H2: 1,
    H3: 1, H4: 1, H5: 1, H6: 1, BR: 1, HR: 1, BLOCKQUOTE: 1, SECTION: 1,
    ARTICLE: 1, HEADER: 1, FOOTER: 1, ASIDE: 1, MAIN: 1, NAV: 1,
    FIGURE: 1, FIGCAPTION: 1, FORM: 1, FIELDSET: 1, CENTER: 1, CAPTION: 1
  };

  function escapeRe(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  /* flags: "gi" für gewöhnliche Begriffe, "g" für Abkürzungen, die
     zeichengenau getroffen werden sollen. */
  function buildPattern(terms, flags) {
    if (!terms || !terms.length) return null;
    var sorted = terms.slice().sort(function (a, b) {
      return b.length - a.length;
    });
    var alts = sorted
      .map(function (t) {
        return escapeRe(String(t).trim())
          // Leerzeichen im Begriff dürfen im Text auch Umbruch sein.
          .replace(/\s+/g, "\\s+")
          // Nach einem Punkt darf das Leerzeichen fehlen: "M.biceps".
          .replace(/\\\.\\s\+/g, "\\.\\s*");
      })
      .join("|");
    try {
      return new RegExp(
        "(?<![" + LETTER + "])(?:" + alts + ")(?![" + LETTER + "])", flags
      );
    } catch (e) {
      return new RegExp("\\b(?:" + alts + ")\\b", flags);
    }
  }

  function isSkipped(el) {
    if (SKIP_TAGS[el.tagName]) return true;
    if (el.classList) {
      if (el.classList.contains("flexikon-term")) return true;
      if (el.classList.contains("flexikon-skip")) return true;
    }
    return false;
  }

  function getRoot() {
    return document.getElementById("qa") || document.body;
  }

  /* Entfernt alle eigenen Marken und stellt den ursprünglichen Text her. */
  function clearMarks(root) {
    var marks = root.querySelectorAll(".flexikon-term");
    if (!marks.length) return;
    var parents = [];
    for (var i = 0; i < marks.length; i++) {
      var span = marks[i];
      var parent = span.parentNode;
      if (!parent) continue;
      while (span.firstChild) parent.insertBefore(span.firstChild, span);
      parent.removeChild(span);
      if (parents.indexOf(parent) < 0) parents.push(parent);
    }
    // Getrennte Textstücke wieder zusammenfügen.
    for (var j = 0; j < parents.length; j++) {
      if (parents[j].normalize) parents[j].normalize();
    }
  }

  /* Sammelt Läufe zusammenhängenden Textes. Ein Lauf ist eine Liste von
     Segmenten {node, start, end} plus der zusammengesetzte Text. */
  function collectRuns(root) {
    var runs = [];
    var current = null;

    function flush() {
      if (current && current.text.trim()) runs.push(current);
      current = null;
    }

    function ensure() {
      if (!current) current = { text: "", segments: [] };
      return current;
    }

    function walk(el) {
      var child = el.firstChild;
      while (child) {
        var next = child.nextSibling;
        if (child.nodeType === 3) {
          var value = child.nodeValue;
          if (value && value.length) {
            var run = ensure();
            run.segments.push({
              node: child,
              start: run.text.length,
              end: run.text.length + value.length
            });
            run.text += value;
          }
        } else if (child.nodeType === 1) {
          if (isSkipped(child)) {
            flush();
          } else if (BLOCK_TAGS[child.tagName]) {
            flush();
            walk(child);
            flush();
          } else {
            walk(child);
          }
        }
        child = next;
      }
    }

    walk(root);
    flush();
    return runs;
  }

  /* Hüllt [from,to) innerhalb eines Textknotens in eine Marke. */
  function wrapRange(node, from, to, term) {
    if (to <= from) return;
    var target = node;
    if (from > 0) target = target.splitText(from);
    if (to - from < target.nodeValue.length) target.splitText(to - from);
    var span = document.createElement("span");
    span.className = "flexikon-term";
    span.setAttribute("data-flexikon-term", term);
    span.setAttribute("title", term + " – im DocCheck Flexikon nachschlagen");
    target.parentNode.replaceChild(span, target);
    span.appendChild(target);
  }

  /* Schlüssel, unter dem ein Fundstück seinem Begriff zugeordnet wird.
     Vereinheitlicht Leerraum und das Leerzeichen nach einem Punkt. */
  function canonKey(text) {
    return String(text)
      .replace(/\s+/g, " ")
      .replace(/\.\s+/g, ".")
      .trim()
      .toLowerCase();
  }

  /* Bereitet eine Anforderung vor.
     terms:   gewöhnliche Begriffe, Groß-/Kleinschreibung egal
     exact:   Abkürzungen, zeichengenau
     aliases: Schreibweise auf der Karte → Artikel, der dafür geöffnet wird,
              z. B. "M. biceps brachii" → "Musculus biceps brachii" */
  function compile(terms, exact, aliases) {
    var surfaces = [];
    var canon = {};
    var i;
    for (i = 0; i < terms.length; i++) {
      canon[canonKey(terms[i])] = String(terms[i]).trim();
    }
    for (i = 0; i < exact.length; i++) {
      canon[canonKey(exact[i])] = String(exact[i]).trim();
    }
    for (var surface in aliases) {
      if (!Object.prototype.hasOwnProperty.call(aliases, surface)) continue;
      surfaces.push(surface);
      canon[canonKey(surface)] = String(aliases[surface]).trim();
    }
    var patterns = [];
    var fuzzy = buildPattern(terms.concat(surfaces), "gi");
    if (fuzzy) patterns.push(fuzzy);
    var strict = buildPattern(exact, "g");
    if (strict) patterns.push(strict);
    return { patterns: patterns, canon: canon };
  }

  function collectMatches(text, pattern, canon) {
    pattern.lastIndex = 0;
    var out = [], m;
    while ((m = pattern.exec(text)) !== null) {
      if (m[0].length === 0) {
        pattern.lastIndex++;
        continue;
      }
      var found = m[0].replace(/\s+/g, " ").trim();
      // Nachgeschlagen wird der hinterlegte Artikel, nicht die Schreibweise
      // der Karte: "corpus luteum" führt zu "Corpus luteum", "M. biceps
      // brachii" zu "Musculus biceps brachii".
      out.push({
        start: m.index,
        end: m.index + m[0].length,
        term: canon[canonKey(found)] || found
      });
    }
    return out;
  }

  /* Bereiche mit Formelquelltext (\( … \), \[ … \]) bleiben unberührt. */
  var TEX_RE = /\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]/g;

  function texRanges(text) {
    if (text.indexOf("\\") < 0) return [];
    var out = [], m;
    TEX_RE.lastIndex = 0;
    while ((m = TEX_RE.exec(text)) !== null) {
      out.push([m.index, m.index + m[0].length]);
    }
    return out;
  }

  function applyRun(run, patterns, canon) {
    var all = [];
    for (var p = 0; p < patterns.length; p++) {
      all = all.concat(collectMatches(run.text, patterns[p], canon));
    }
    if (!all.length) return;

    var blocked = texRanges(run.text);
    if (blocked.length) {
      all = all.filter(function (m) {
        for (var b = 0; b < blocked.length; b++) {
          if (m.start < blocked[b][1] && m.end > blocked[b][0]) return false;
        }
        return true;
      });
      if (!all.length) return;
    }

    // Links vor rechts, bei gleichem Anfang der längere Treffer. So gewinnt
    // "LH-Analogon" gegen "LH" und "Corpus luteum gravidarum" gegen
    // "Corpus luteum", gleich aus welchem Muster sie stammen.
    all.sort(function (a, b) {
      if (a.start !== b.start) return a.start - b.start;
      return (b.end - b.start) - (a.end - a.start);
    });
    var matches = [];
    var lastEnd = -1;
    for (var q = 0; q < all.length; q++) {
      if (all[q].start >= lastEnd) {
        matches.push(all[q]);
        lastEnd = all[q].end;
      }
    }

    // Von hinten nach vorn, damit die Knoten-Offsets gültig bleiben.
    for (var i = matches.length - 1; i >= 0; i--) {
      var match = matches[i];
      var pieces = [];
      for (var s = 0; s < run.segments.length; s++) {
        var seg = run.segments[s];
        var from = Math.max(match.start, seg.start);
        var to = Math.min(match.end, seg.end);
        if (from < to) {
          pieces.push({
            node: seg.node,
            from: from - seg.start,
            to: to - seg.start
          });
        }
      }
      for (var j = pieces.length - 1; j >= 0; j--) {
        var piece = pieces[j];
        if (!piece.node.parentNode) continue;
        // Reine Leerzeichen-Teilstücke brauchen keine Marke.
        var slice = piece.node.nodeValue.slice(piece.from, piece.to);
        if (!slice.trim()) continue;
        wrapRange(piece.node, piece.from, piece.to, match.term);
      }
    }
  }

  function countMarks(root) {
    return root.querySelectorAll(".flexikon-term").length;
  }

  /* Wendet die gemerkte Anforderung auf den aktuellen Karteninhalt an. */
  function applyRequest() {
    if (!request) return;
    var root = getRoot();
    if (observer) observer.disconnect();
    try {
      clearMarks(root);
      if (request.patterns.length) {
        var runs = collectRuns(root);
        for (var i = 0; i < runs.length; i++) {
          applyRun(runs[i], request.patterns, request.canon);
        }
      }
    } catch (e) {
      if (window.console) console.log("[Flexikon] Markierung:", e);
    }
    lastText = root.textContent;
    lastCount = countMarks(root);
    watch(root);
  }

  function watch(root) {
    if (typeof MutationObserver === "undefined") return;
    if (!observer) observer = new MutationObserver(onMutation);
    observer.observe(root, {
      childList: true, subtree: true, characterData: true
    });
  }

  /* Der Karteninhalt hat sich geändert (neue Karte, Antwortseite, spät
     geladenes Bild, Formelsatz). Nur wenn Text oder Marken wirklich anders
     sind, wird neu markiert. */
  function onMutation() {
    if (timer || !request) return;
    timer = setTimeout(function () {
      timer = null;
      if (!request || reapplies >= MAX_REAPPLIES) return;
      var root = getRoot();
      if (root.textContent !== lastText || countMarks(root) !== lastCount) {
        reapplies++;
        applyRequest();
      }
    }, 0);
  }

  function setOptions(opts) {
    if (!opts) return;
    if ("doubleClick" in opts) options.doubleClick = !!opts.doubleClick;
    if (opts.style) options.style = String(opts.style);
    if (document.body) {
      document.body.setAttribute("data-flexikon-style", options.style || "dotted");
    }
  }

  window.flexikonHighlight = function (terms, opts) {
    opts = opts || {};
    setOptions(opts);
    request = compile(terms || [], opts.exact || [], opts.aliases || {});
    reapplies = 0;
    applyRequest();
  };

  window.flexikonSetOptions = setOptions;

  document.addEventListener("click", function (ev) {
    var el = ev.target;
    while (el && el !== document.body) {
      if (el.classList && el.classList.contains("flexikon-term")) {
        ev.preventDefault();
        ev.stopPropagation();
        pycmd("flexikon-lookup:" + el.getAttribute("data-flexikon-term"));
        return;
      }
      el = el.parentElement;
    }
  }, true);

  document.addEventListener("dblclick", function (ev) {
    if (!options.doubleClick) return;
    var el = ev.target;
    while (el && el !== document.body) {
      if (el.classList && el.classList.contains("flexikon-term")) return;
      el = el.parentElement;
    }
    var sel = window.getSelection ? String(window.getSelection()) : "";
    sel = sel.replace(/\s+/g, " ").trim();
    if (!sel || sel.length < 3 || sel.length > 80) return;
    pycmd("flexikon-lookup:" + sel);
  }, true);
})();
