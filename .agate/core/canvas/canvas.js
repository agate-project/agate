/* Agate canvas · generic pan/zoom board engine.
 *
 * Reads canvas.json (next to index.html) and draws each board (its own HTML file in boards/) as an artboard.
 * Format (everything optional has a default):
 * {
 *   "title": "…", "description": "…", "lang": "en|es|…", "created": "YYYY-MM-DD", "entry": "<board id>",
 *   "links": [{ "label": "…", "href": "…" }]  (optional: header links),
 *   "sections": [{ "id": "…", "title": "…", "subtitle": "…" }],
 *   "boards":   [{ "id": "…", "title": "…", "src": "boards/x.html", "section": "…",
 *                  "preset": "mobile|tablet|laptop|desktop|a4|square|story", "w": 0, "h": 0,
 *                  "x": 0, "y": 0, "note": "…", "status": "pending" }],
 *   "notes":    [{ "section": "…", "text": "…", "w": 280, "x": 0, "y": 0, "color": "yellow|blue|green|pink" }],
 *   "arrows":   [{ "from": "<id>", "to": "<id>", "label": "…" }]
 * }
 * A board or note without x/y is laid out automatically inside its section (rows from left to right).
 * Interface language: "lang" in canvas.json, else <html lang>, else the browser language; English by default.
 * To add a language, add an entry to I18N below with the same keys as "en".
 * Serve it with `python3 .agate/agate.py serve` (comments on) or `python3 -m http.server` (read-only) from the
 * repo root. Comments: comments.js (same folder) is loaded automatically and uses window.AgateCanvas below.
 */
(function () {
  "use strict";
  var SELF = document.currentScript && document.currentScript.src;

  var PRESETS = {
    mobile: [390, 844], tablet: [834, 1194], laptop: [1280, 800], desktop: [1440, 900],
    a4: [794, 1123], square: [1080, 1080], story: [1080, 1920]
  };
  var MIN_Z = 0.03, MAX_Z = 4, GAP = 96, ROW_MAX = 5200, SECTION_HEAD = 340, SECTION_GAP = 320;
  var LABEL_H = 34;

  // ---------- interface language ----------
  var I18N = {
    en: {
      other: "Other",
      open: "open ↗", openTitle: "Open in a new tab",
      pending: "Pending", pendingNote: "This screen hasn't been made yet.",
      goTo: "Go to", goToEllipsis: "Go to…", wholeSection: "Whole section",
      zoomOut: "Zoom out", zoom100: "Zoom to 100%", zoomIn: "Zoom in", fit: "Fit all",
      minimap: "Minimap", minimapTitle: "Minimap (M)", shortcuts: "Shortcuts", shortcutsTitle: "Shortcuts (?)",
      helpTitle: "How to move around",
      help: ["Drag: pan · wheel or pinch: zoom",
             "Click: select · double-click: frame the screen and use it (scroll, buttons)",
             "<kbd>Esc</kbd> leave the screen · click the background: release",
             "<kbd>0</kbd> fit all · <kbd>1</kbd> 100% · <kbd>+</kbd>/<kbd>−</kbd> zoom",
             "<kbd>←</kbd>/<kbd>→</kbd> previous/next screen · <kbd>M</kbd> minimap",
             "Link to a screen: <code>#id</code> in the URL"],
      errorTitle: "The canvas could not be opened.",
      errorServe: "It has to be served by a local server, from the repo root:",
      errorStatus: "canvas.json returned"
    },
    es: {
      other: "Otros",
      open: "abrir ↗", openTitle: "Abrir en otra pestaña",
      pending: "Pendiente", pendingNote: "Todavía no se hizo esta pantalla.",
      goTo: "Ir a", goToEllipsis: "Ir a…", wholeSection: "Toda la sección",
      zoomOut: "Alejar", zoom100: "Zoom al 100 %", zoomIn: "Acercar", fit: "Ver todo",
      minimap: "Minimapa", minimapTitle: "Minimapa (M)", shortcuts: "Atajos", shortcutsTitle: "Atajos (?)",
      helpTitle: "Cómo moverse",
      help: ["Arrastrar: mover · rueda o pellizco: zoom",
             "Clic: seleccionar · doble clic: encuadrar y usar la pantalla (scroll, botones)",
             "<kbd>Esc</kbd> salir de la pantalla · clic en el fondo: soltar",
             "<kbd>0</kbd> ver todo · <kbd>1</kbd> 100 % · <kbd>+</kbd>/<kbd>−</kbd> zoom",
             "<kbd>←</kbd>/<kbd>→</kbd> pantalla anterior/siguiente · <kbd>M</kbd> minimapa",
             "Enlace a una pantalla: <code>#id</code> en la URL"],
      errorTitle: "No se pudo abrir el canvas.",
      errorServe: "Hay que servirlo con un servidor local, desde la raíz del repo:",
      errorStatus: "canvas.json respondió"
    }
  };
  var LANG = pickLang();
  function pickLang(explicit) {
    var cands = [explicit, document.documentElement.getAttribute("lang")]
      .concat(navigator.languages || [navigator.language]);
    for (var i = 0; i < cands.length; i++) {
      var c = String(cands[i] || "").toLowerCase().split(/[-_]/)[0];
      if (I18N[c]) return c;
    }
    return "en";
  }
  function t(key) { var d = I18N[LANG] || I18N.en; return d[key] != null ? d[key] : I18N.en[key]; }

  var S = { x: 0, y: 0, z: 1 };
  var data, vp, world, svg, mini, miniCtx, zoomOut, helpBox, items = [], byId = {}, sectionEls = [];
  var active = null, idle = 0, bounds = { x: 0, y: 0, w: 1, h: 1 };

  // ---------- helpers ----------
  function el(tag, cls, parent, html) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    if (parent) parent.appendChild(n);
    return n;
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }

  // ---------- view ----------
  function apply() {
    world.style.transform = "translate(" + S.x + "px," + S.y + "px) scale(" + S.z + ")";
    // will-change only while moving: if left on, Chrome keeps the old bitmap and everything looks blurry.
    world.classList.add("moving");
    clearTimeout(idle);
    idle = setTimeout(function () { world.classList.remove("moving"); lazyLoad(); drawMini(); }, 160);
    // Labels keep a readable size when zooming in; when zooming far out they shrink with the board and,
    // at very far zoom, hide (section titles and the minimap are read there).
    var inv = Math.min(1 / S.z, 1 / 0.35), hide = S.z < 0.2;
    for (var i = 0; i < items.length; i++) {
      var it = items[i];
      if (!it.label) continue;
      it.label.style.transform = "scale(" + inv + ")";
      it.label.style.maxWidth = Math.max(40, it.w / inv) + "px";
      it.label.style.opacity = hide ? "0" : "";
    }
    document.body.classList.toggle("cv-far", hide);
    vp.style.backgroundSize = 32 * S.z + "px " + 32 * S.z + "px";
    vp.style.backgroundPosition = S.x + "px " + S.y + "px";
    zoomOut.textContent = Math.round(S.z * 100) + "%";
    drawMini();
    for (var v = 0; v < API.views.length; v++) { try { API.views[v](); } catch (err) { /* a listener never breaks the view */ } }
  }
  function zoomAt(cx, cy, k) {
    var nz = clamp(S.z * k, MIN_Z, MAX_Z);
    S.x = cx - (cx - S.x) * (nz / S.z);
    S.y = cy - (cy - S.y) * (nz / S.z);
    S.z = nz;
    apply();
  }
  function fitRect(r, pad) {
    pad = pad == null ? 60 : pad;
    var bar = document.querySelector(".cv-bar");
    var W = vp.clientWidth, H = vp.clientHeight, top = bar ? bar.offsetHeight + 16 : 64; // room for the bar
    var z = clamp(Math.min((W - pad * 2) / r.w, (H - top - pad * 2) / r.h), MIN_Z, MAX_Z);
    S.z = z;
    S.x = (W - r.w * z) / 2 - r.x * z;
    S.y = top + (H - top - r.h * z) / 2 - r.y * z;
    apply();
  }
  function fitAll() { fitRect(bounds, 40); }
  function focusItem(it, keepHash) {
    if (!it) return;
    fitRect({ x: it.x, y: it.y - LABEL_H, w: it.w, h: it.h + LABEL_H }, 48);
    flash(it.node);
    if (!keepHash && it.kind === "board") history.replaceState(null, "", "#" + it.id);
  }
  function flash(node) {
    node.classList.remove("cv-flash");
    void node.offsetWidth;
    node.classList.add("cv-flash");
  }

  // ---------- layout ----------
  function size(b) {
    var p = PRESETS[b.preset] || [];
    return [b.w || p[0] || 800, b.h || p[1] || 600];
  }
  function layout() {
    var secs = (data.sections || []).slice();
    var ids = {};
    secs.forEach(function (s) { ids[s.id] = true; });
    var orphan = (data.boards || []).concat(data.notes || []).some(function (b) { return !b.section || !ids[b.section]; });
    if (orphan) secs.push({ id: "__sin", title: secs.length ? t("other") : "" });

    var y = 0;
    secs.forEach(function (sec, si) {
      var mine = [];
      (data.boards || []).forEach(function (b) {
        if ((b.section && ids[b.section] ? b.section : "__sin") === sec.id) mine.push({ kind: "board", d: b });
      });
      (data.notes || []).forEach(function (n) {
        if ((n.section && ids[n.section] ? n.section : "__sin") === sec.id) mine.push({ kind: "note", d: n });
      });
      if (!mine.length && !sec.title) return;
      var sx = 0, sy = y, x = 0, rowY = y + (sec.title ? SECTION_HEAD : 0), rowH = 0, maxX = 0;
      mine.forEach(function (m) {
        var d = m.d, wh = m.kind === "board" ? size(d) : [d.w || 300, d.h || 0];
        var it = { kind: m.kind, d: d, id: d.id || ("note-" + items.length), w: wh[0], h: wh[1], section: sec.id };
        if (d.x != null && d.y != null) { it.x = d.x; it.y = d.y; }
        else {
          if (x > 0 && x + it.w > ROW_MAX) { x = 0; rowY += rowH + GAP + LABEL_H; rowH = 0; }
          it.x = x; it.y = rowY + LABEL_H;
          x += it.w + GAP;
          rowH = Math.max(rowH, it.h || 260);
          maxX = Math.max(maxX, x - GAP);
        }
        items.push(it);
        if (it.kind === "board") byId[it.id] = it;
      });
      var secH = rowY + rowH + LABEL_H - sy;
      sectionEls.push({ sec: sec, index: si, x: sx, y: sy, w: Math.max(maxX, 900), h: secH });
      y = sy + secH + SECTION_GAP;
    });
  }

  // ---------- drawing ----------
  function render() {
    var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    function grow(x, y, w, h) { minX = Math.min(minX, x); minY = Math.min(minY, y); maxX = Math.max(maxX, x + w); maxY = Math.max(maxY, y + h); }

    sectionEls.forEach(function (s) {
      if (!s.sec.title) return;
      var head = el("div", "cv-section", world);
      head.style.left = s.x + "px";
      head.style.top = s.y + "px";
      head.id = "section-" + s.sec.id;
      el("div", "cv-section-num", head, String(s.index + 1).padStart(2, "0"));
      el("div", "cv-section-title", head, esc(s.sec.title));
      if (s.sec.subtitle) el("div", "cv-section-sub", head, esc(s.sec.subtitle));
      grow(s.x, s.y, s.w, s.h);
    });

    items.forEach(function (it) {
      var d = it.d;
      if (it.kind === "note") {
        var n = el("div", "cv-note cv-note-" + (d.color || "yellow"), world);
        n.style.left = it.x + "px"; n.style.top = it.y + "px"; n.style.width = it.w + "px";
        if (it.h) n.style.minHeight = it.h + "px";
        n.innerHTML = esc(d.text).replace(/\n/g, "<br>");
        it.node = n;
        grow(it.x, it.y, it.w, Math.max(it.h, n.offsetHeight || 160));
        return;
      }
      var b = el("div", "cv-board" + (d.status === "pending" ? " cv-pending" : ""), world);
      b.style.left = it.x + "px"; b.style.top = it.y + "px";
      b.style.width = it.w + "px"; b.style.height = it.h + "px";
      b.dataset.id = it.id;
      var lab = el("div", "cv-label", b);
      lab.innerHTML = '<span class="cv-label-title">' + esc(d.title || it.id) + "</span>" +
        '<span class="cv-label-meta">' + it.w + "×" + it.h + "</span>" +
        (d.src && d.status !== "pending" ? '<a class="cv-open" href="' + esc(d.src) + '" target="_blank" rel="noopener" title="' + esc(t("openTitle")) + '">' + esc(t("open")) + "</a>" : "");
      it.label = lab;
      if (d.status === "pending") {
        el("div", "cv-pending-body", b, "<b>" + esc(t("pending")) + "</b><span>" + esc(d.note || t("pendingNote")) + "</span>");
      } else {
        var f = el("iframe", "cv-frame", b);
        f.setAttribute("title", d.title || it.id);
        f.setAttribute("loading", "lazy");
        f.setAttribute("sandbox", "allow-scripts allow-same-origin allow-popups allow-forms");
        f.dataset.src = d.src;
        // Esc also works with focus inside the screen (same origin).
        f.addEventListener("load", function () {
          try {
            f.contentWindow.addEventListener("keydown", function (ev) {
              if (ev.key === "Escape") { deactivate(); window.focus(); }
            });
          } catch (err) { /* other origin: Esc only from the canvas */ }
        });
        it.frame = f;
        el("div", "cv-shield", b); // layer that stops the iframe from eating the drag until it is activated
        if (d.note) {
          var nt = el("div", "cv-board-note", b, esc(d.note));
          nt.style.top = (it.h + 14) + "px";
        }
      }
      it.node = b;
      grow(it.x, it.y - LABEL_H, it.w, it.h + LABEL_H + (d.note ? 70 : 0));
    });

    drawArrows();
    if (minX === Infinity) { minX = minY = 0; maxX = maxY = 100; }
    bounds = { x: minX, y: minY, w: maxX - minX, h: maxY - minY };
    world.style.width = maxX + "px";
    world.style.height = maxY + "px";
  }

  function drawArrows() {
    var arrows = data.arrows || [];
    if (!arrows.length) return;
    svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "cv-arrows");
    svg.innerHTML = '<defs><marker id="cv-head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" class="cv-arrow-head"/></marker></defs>';
    world.appendChild(svg);
    arrows.forEach(function (a) {
      var A = byId[a.from], B = byId[a.to];
      if (!A || !B) return;
      var ac = { x: A.x + A.w / 2, y: A.y + A.h / 2 }, bc = { x: B.x + B.w / 2, y: B.y + B.h / 2 };
      var p1 = edge(A, bc), p2 = edge(B, ac);
      var mx = (p1.x + p2.x) / 2, my = (p1.y + p2.y) / 2;
      var path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      var dx = Math.abs(p2.x - p1.x) * 0.35;
      path.setAttribute("d", "M" + p1.x + " " + p1.y + " C" + (p1.x + (p2.x > p1.x ? dx : -dx)) + " " + p1.y + " " + (p2.x - (p2.x > p1.x ? dx : -dx)) + " " + p2.y + " " + p2.x + " " + p2.y);
      path.setAttribute("class", "cv-arrow");
      path.setAttribute("marker-end", "url(#cv-head)");
      svg.appendChild(path);
      if (a.label) {
        var t = el("div", "cv-arrow-label", world, esc(a.label));
        t.style.left = mx + "px"; t.style.top = my + "px";
      }
    });
  }
  function edge(r, toward) {
    var cx = r.x + r.w / 2, cy = r.y + r.h / 2, dx = toward.x - cx, dy = toward.y - cy;
    if (!dx && !dy) return { x: cx, y: cy };
    var sx = (r.w / 2 + 14) / Math.abs(dx || 1e-9), sy = (r.h / 2 + 14) / Math.abs(dy || 1e-9), s = Math.min(sx, sy);
    return { x: cx + dx * s, y: cy + dy * s };
  }

  // Loads iframes only when their board is near the viewport (performance with many boards).
  function lazyLoad() {
    var W = vp.clientWidth, H = vp.clientHeight, m = 300;
    items.forEach(function (it) {
      if (!it.frame || it.frame.src) return;
      var l = it.x * S.z + S.x, t = it.y * S.z + S.y, r = l + it.w * S.z, b = t + it.h * S.z;
      if (r > -m && l < W + m && b > -m && t < H + m) it.frame.src = it.frame.dataset.src;
    });
  }

  // ---------- activate a board (to scroll or click inside it) ----------
  function activate(it) {
    if (active === it) return;
    deactivate();
    if (!it || !it.frame) return;
    active = it;
    if (!it.frame.src) it.frame.src = it.frame.dataset.src;
    it.node.classList.add("cv-active");
    document.body.classList.add("cv-has-active");
  }
  var selected = null;
  function select(it) {
    if (selected) selected.node.classList.remove("cv-selected");
    selected = it || null;
    if (selected) selected.node.classList.add("cv-selected");
  }
  function deactivate() {
    if (!active) return;
    active.node.classList.remove("cv-active");
    active = null;
    document.body.classList.remove("cv-has-active");
  }

  // ---------- minimap ----------
  function drawMini() {
    if (!miniCtx || mini.parentNode.hidden) return;
    var cw = mini.width, ch = mini.height, k = Math.min(cw / bounds.w, ch / bounds.h) * 0.92;
    var ox = (cw - bounds.w * k) / 2 - bounds.x * k, oy = (ch - bounds.h * k) / 2 - bounds.y * k;
    mini._t = { k: k, ox: ox, oy: oy };
    var cs = getComputedStyle(document.documentElement);
    miniCtx.clearRect(0, 0, cw, ch);
    items.forEach(function (it) {
      miniCtx.fillStyle = it.kind === "note" ? cs.getPropertyValue("--cv-note-yellow").trim() :
        (it.d.status === "pending" ? cs.getPropertyValue("--cv-line").trim() : cs.getPropertyValue("--cv-mini-board").trim());
      miniCtx.fillRect(ox + it.x * k, oy + it.y * k, Math.max(2, it.w * k), Math.max(2, (it.h || 120) * k));
    });
    var vx = (-S.x / S.z) * k + ox, vy = (-S.y / S.z) * k + oy, vw = (vp.clientWidth / S.z) * k, vh = (vp.clientHeight / S.z) * k;
    miniCtx.strokeStyle = cs.getPropertyValue("--cv-accent").trim();
    miniCtx.lineWidth = 2;
    miniCtx.strokeRect(vx, vy, vw, vh);
  }
  function miniGo(e) {
    var r = mini.getBoundingClientRect(), t = mini._t;
    if (!t) return;
    var px = (e.clientX - r.left) * (mini.width / r.width), py = (e.clientY - r.top) * (mini.height / r.height);
    var wx = (px - t.ox) / t.k, wy = (py - t.oy) / t.k;
    S.x = vp.clientWidth / 2 - wx * S.z;
    S.y = vp.clientHeight / 2 - wy * S.z;
    apply();
  }

  // ---------- interface ----------
  function buildUI() {
    document.title = data.title || "Canvas";
    var bar = el("header", "cv-bar", document.body);
    var left = el("div", "cv-bar-left", bar);
    el("div", "cv-title", left, esc(data.title || "Canvas"));
    if (data.created || data.description) el("div", "cv-sub", left, esc([data.created, data.description].filter(Boolean).join(" · ")));
    // Optional links to other canvases or pages: "links": [{ "label": "…", "href": "…" }]
    if (data.links && data.links.length) {
      var lk = el("div", "cv-links", left);
      data.links.forEach(function (l) { var x = el("a", "", lk, esc(l.label || l.href)); x.href = l.href; });
    }

    var right = el("div", "cv-bar-right", bar);
    var jump = el("select", "cv-jump", right);
    jump.setAttribute("aria-label", t("goTo"));
    jump.innerHTML = '<option value="">' + esc(t("goToEllipsis")) + "</option>" +
      sectionEls.filter(function (s) { return s.sec.title; }).map(function (s) {
        var opts = items.filter(function (it) { return it.kind === "board" && it.section === s.sec.id; })
          .map(function (it) { return '<option value="b:' + esc(it.id) + '">  ' + esc(it.d.title || it.id) + "</option>"; }).join("");
        return '<optgroup label="' + esc(s.sec.title) + '"><option value="s:' + esc(s.sec.id) + '">' + esc(t("wholeSection")) + "</option>" + opts + "</optgroup>";
      }).join("");
    jump.addEventListener("change", function () {
      var v = jump.value; jump.value = "";
      if (v.indexOf("b:") === 0) focusItem(byId[v.slice(2)]);
      else if (v.indexOf("s:") === 0) {
        var s = sectionEls.filter(function (x) { return x.sec.id === v.slice(2); })[0];
        if (s) fitRect({ x: s.x, y: s.y, w: s.w, h: s.h }, 40);
      }
    });

    var z = el("div", "cv-zoom", right);
    z.innerHTML = '<button type="button" data-a="out" aria-label="' + esc(t("zoomOut")) + '">−</button>' +
      '<button type="button" data-a="100" class="cv-pct" aria-label="' + esc(t("zoom100")) + '">100%</button>' +
      '<button type="button" data-a="in" aria-label="' + esc(t("zoomIn")) + '">+</button>' +
      '<button type="button" data-a="fit" class="cv-fit" aria-label="' + esc(t("fit")) + '">' + esc(t("fit")) + "</button>" +
      '<button type="button" data-a="mini" aria-label="' + esc(t("minimap")) + '" title="' + esc(t("minimapTitle")) + '">▦</button>' +
      '<button type="button" data-a="help" aria-label="' + esc(t("shortcuts")) + '" title="' + esc(t("shortcutsTitle")) + '">?</button>';
    zoomOut = z.querySelector(".cv-pct");
    z.addEventListener("click", function (e) {
      var b = e.target.closest("button");
      if (!b) return;
      var a = b.dataset.a, W = vp.clientWidth / 2, H = vp.clientHeight / 2;
      if (a === "in") zoomAt(W, H, 1.4);
      else if (a === "out") zoomAt(W, H, 1 / 1.4);
      else if (a === "100") zoomAt(W, H, 1 / S.z);
      else if (a === "fit") fitAll();
      else if (a === "mini") toggleMini();
      else if (a === "help") helpBox.hidden = !helpBox.hidden;
    });

    var mw = el("div", "cv-mini", document.body);
    mini = el("canvas", "", mw);
    mini.width = 220; mini.height = 150;
    miniCtx = mini.getContext("2d");
    mw.hidden = matchMedia("(max-width: 700px)").matches;
    var miniDown = false;
    mini.addEventListener("pointerdown", function (e) { miniDown = true; mini.setPointerCapture(e.pointerId); miniGo(e); });
    mini.addEventListener("pointermove", function (e) { if (miniDown) miniGo(e); });
    mini.addEventListener("pointerup", function () { miniDown = false; });

    helpBox = el("div", "cv-help", document.body,
      "<b>" + esc(t("helpTitle")) + "</b><ul><li>" + t("help").join("</li><li>") + "</li></ul>");
    helpBox.hidden = true;
    helpBox.addEventListener("click", function () { helpBox.hidden = true; });
  }
  function toggleMini() { mini.parentNode.hidden = !mini.parentNode.hidden; drawMini(); }

  // ---------- gestures (one finger pans, two pinch) ----------
  function bindInput() {
    var pts = new Map(), drag = null, pinch = null, lastTap = 0, moved = 0, downAt = null;
    function pinchState() {
      var v = Array.from(pts.values()), a = v[0], b = v[1];
      return { d: Math.hypot(a.x - b.x, a.y - b.y), cx: (a.x + b.x) / 2, cy: (a.y + b.y) / 2 };
    }
    vp.addEventListener("pointerdown", function (e) {
      if (e.target.closest("a, button, select, .cv-active iframe")) return;
      if (e.button !== undefined && e.button > 1) return;
      if (e.pointerType === "mouse") e.preventDefault(); // keeps dragging from starting a text selection
      vp.setPointerCapture(e.pointerId);
      pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pts.size === 2) { drag = null; pinch = pinchState(); return; }
      downAt = { x: e.clientX, y: e.clientY, t: Date.now(), target: e.target };
      moved = 0;
      if (e.pointerType === "touch") {
        var now = Date.now();
        if (now - lastTap < 300) { dbl(e); lastTap = 0; } else lastTap = now;
      }
      drag = { x: e.clientX - S.x, y: e.clientY - S.y };
      vp.classList.add("cv-panning");
    });
    vp.addEventListener("pointermove", function (e) {
      if (!pts.has(e.pointerId)) return;
      pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pinch && pts.size === 2) {
        var now = pinchState();
        zoomAt(now.cx, now.cy, now.d / pinch.d);
        S.x += now.cx - pinch.cx; S.y += now.cy - pinch.cy;
        apply();
        pinch = now;
        return;
      }
      if (!drag) return;
      if (downAt) moved = Math.max(moved, Math.hypot(e.clientX - downAt.x, e.clientY - downAt.y));
      S.x = e.clientX - drag.x; S.y = e.clientY - drag.y;
      apply();
    });
    function end(e) {
      pts.delete(e.pointerId);
      if (pts.size < 2) pinch = null;
      if (pts.size === 1) { var p = Array.from(pts.values())[0]; drag = { x: p.x - S.x, y: p.y - S.y }; return; }
      // A click without dragging on a board selects it; on the background, it deactivates.
      if (downAt && moved < 5 && e.type === "pointerup" && API.click) {
        API.click(e.clientX, e.clientY);
        drag = null; downAt = null; vp.classList.remove("cv-panning");
        return;
      }
      if (downAt && moved < 5 && e.type === "pointerup") {
        var bn = downAt.target.closest && downAt.target.closest(".cv-board");
        if (bn) select(byId[bn.dataset.id]); else { select(null); deactivate(); }
      }
      drag = null; downAt = null;
      vp.classList.remove("cv-panning");
    }
    vp.addEventListener("pointerup", end);
    vp.addEventListener("pointercancel", end);
    vp.addEventListener("dblclick", dbl);
    // Double-click (or double-tap) on a screen: frames it and makes it usable.
    function dbl(e) {
      var t = document.elementFromPoint(e.clientX, e.clientY);
      var bn = t && t.closest && t.closest(".cv-board");
      if (bn) { var it = byId[bn.dataset.id]; focusItem(it); activate(it); }
      else zoomAt(e.clientX, e.clientY, 2);
    }
    // Wheel: zoom towards the cursor. With Shift, or horizontal trackpad scrolling, it pans.
    vp.addEventListener("wheel", function (e) {
      if (e.target.closest(".cv-active")) return;
      e.preventDefault();
      if (e.shiftKey || (Math.abs(e.deltaX) > Math.abs(e.deltaY) && !e.ctrlKey)) {
        S.x -= e.deltaX || e.deltaY; S.y -= e.shiftKey ? 0 : e.deltaY; apply(); return;
      }
      var unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1;
      var k = Math.exp(-e.deltaY * unit * (e.ctrlKey ? 0.01 : 0.0015));
      zoomAt(e.clientX, e.clientY, k);
    }, { passive: false });
    vp.addEventListener("dragstart", function (e) { e.preventDefault(); });
    // No selection on the canvas: neither when dragging nor when double-clicking titles or notes.
    vp.addEventListener("selectstart", function (e) { e.preventDefault(); });
    vp.addEventListener("dblclick", function () { var s = window.getSelection && window.getSelection(); if (s) s.removeAllRanges(); });

    addEventListener("keydown", function (e) {
      if (e.target.closest && e.target.closest("input, textarea, select")) return;
      var W = vp.clientWidth / 2, H = vp.clientHeight / 2;
      if (e.key === "Escape") { deactivate(); helpBox.hidden = true; }
      else if (active) return;
      else if (e.key === "0") fitAll();
      else if (e.key === "1") zoomAt(W, H, 1 / S.z);
      else if (e.key === "+" || e.key === "=") zoomAt(W, H, 1.4);
      else if (e.key === "-" || e.key === "_") zoomAt(W, H, 1 / 1.4);
      else if (e.key === "m" || e.key === "M") toggleMini();
      else if (e.key === "?") helpBox.hidden = !helpBox.hidden;
      else if (e.key === "ArrowRight" || e.key === "ArrowLeft") step(e.key === "ArrowRight" ? 1 : -1);
    });
    addEventListener("resize", function () { apply(); });
    addEventListener("hashchange", function () { var it = byId[location.hash.slice(1)]; if (it) focusItem(it, true); });
  }
  var cursor = -1;
  function step(dir) {
    var boards = items.filter(function (it) { return it.kind === "board"; });
    if (!boards.length) return;
    cursor = (cursor + dir + boards.length) % boards.length;
    focusItem(boards[cursor]);
  }

  // ---------- API for comments.js (and other overlays) ----------
  // Screen ↔ world coordinates, which board is under a point, a view-change hook and a click hook (comment mode).
  var API = {
    views: [], click: null,
    lang: function () { return LANG; },
    bar: function () { return document.querySelector(".cv-bar-right"); },
    toWorld: function (cx, cy) { return { x: (cx - S.x) / S.z, y: (cy - S.y) / S.z }; },
    toScreen: function (x, y) { return { x: x * S.z + S.x, y: y * S.z + S.y }; },
    boardAt: function (cx, cy) {
      var w = API.toWorld(cx, cy);
      for (var i = items.length - 1; i >= 0; i--) {
        var it = items[i];
        if (it.kind !== "board") continue;
        if (w.x >= it.x && w.x <= it.x + it.w && w.y >= it.y && w.y <= it.y + it.h) {
          return { id: it.id, rx: (w.x - it.x) / it.w, ry: (w.y - it.y) / it.h, title: it.d.title || it.id };
        }
      }
      return null;
    },
    board: function (id) {
      var it = byId[id];
      return it && it.kind === "board" ? { x: it.x, y: it.y, w: it.w, h: it.h, title: it.d.title || it.id } : null;
    },
    focusBoard: function (id) { var it = byId[id]; if (it) focusItem(it, true); },
    focusPoint: function (x, y) {
      S.x = vp.clientWidth / 2 - x * S.z; S.y = vp.clientHeight / 2 - y * S.z; apply();
    },
    onView: function (fn) { API.views.push(fn); },
    setClick: function (fn) { API.click = fn || null; vp.classList.toggle("cv-commenting", !!fn); }
  };
  function loadComments() {
    window.AgateCanvas = API;
    try { window.dispatchEvent(new Event("agate-canvas-ready")); } catch (err) { /* old browsers */ }
    if (!SELF || document.querySelector("script[data-agate-comments]")) return;
    var sc = document.createElement("script");
    sc.src = SELF.replace(/canvas\.js(\?.*)?$/, "comments.js");
    sc.defer = true;
    sc.setAttribute("data-agate-comments", "");
    document.head.appendChild(sc);
  }

  // ---------- startup ----------
  function start(json) {
    data = json;
    LANG = pickLang(json.lang);
    if (json.lang) document.documentElement.setAttribute("lang", json.lang);
    vp = el("main", "cv-viewport", document.body);
    world = el("div", "cv-world", vp);
    layout();
    render();
    buildUI();
    bindInput();
    var first = byId[decodeURIComponent(location.hash.slice(1))] || null;
    if (first) focusItem(first, true); else fitAll();
    lazyLoad();
    loadComments();
  }
  function fail(msg) {
    document.body.innerHTML = '<div class="cv-error"><b>' + esc(t("errorTitle")) + "</b><p>" + esc(msg) +
      "</p><p>" + esc(t("errorServe")) + "</p><pre>python3 -m http.server 8090</pre></div>";
  }
  fetch("canvas.json", { cache: "no-store" })
    .then(function (r) { if (!r.ok) throw new Error(t("errorStatus") + " " + r.status); return r.json(); })
    .then(start)
    .catch(function (e) { fail(e.message || String(e)); });
})();
