/* Agate comments · pins and threads on canvases and HTML artifacts.
 *
 * Canvas: loaded automatically by canvas.js (uses window.AgateCanvas).
 * Any other artifact: <script src="../../.agate/core/canvas/comments.js" defer></script> (adjust the depth).
 * Needs `python3 .agate/agate.py serve` to write; with a plain static server it shows comments read-only.
 * Comments are stored next to the artifact (canvas: comments.json; x.html: x.comments.json).
 * Text is always rendered with textContent (never as HTML).
 */
(function () {
  "use strict";
  if (window.__agateComments) return;
  window.__agateComments = true;

  var I18N = {
    en: {
      comment: "Comment", commentTitle: "Comment mode (C)", comments: "Comments", close: "Close",
      placeholder: "Write a comment…", save: "Comment", cancel: "Cancel", reply: "Reply", replyPh: "Reply…",
      resolve: "Resolve", reopen: "Reopen", resolved: "resolved", showResolved: "Show resolved",
      none: "No comments yet. Turn on comment mode and click where you want to leave one.",
      readonly: "Read-only. To comment, start the viewer from the project root:",
      yourName: "Your name (shown with your comments)", clickHint: "Click on a screen or on the canvas to leave a comment",
      pageHint: "Click on the page to leave a comment (select text first to quote it)",
      error: "Could not save", page: "page", canvas: "canvas"
    },
    es: {
      comment: "Comentar", commentTitle: "Modo comentario (C)", comments: "Comentarios", close: "Cerrar",
      placeholder: "Escribe un comentario…", save: "Comentar", cancel: "Cancelar", reply: "Responder", replyPh: "Responder…",
      resolve: "Resolver", reopen: "Reabrir", resolved: "resuelto", showResolved: "Ver resueltos",
      none: "Todavía no hay comentarios. Activa el modo comentario y haz clic donde quieras dejar uno.",
      readonly: "Solo lectura. Para comentar, inicia el visor desde la raíz del proyecto:",
      yourName: "Tu nombre (se muestra con tus comentarios)", clickHint: "Haz clic en una pantalla o en el lienzo para comentar",
      pageHint: "Haz clic en la página para comentar (selecciona texto antes para citarlo)",
      error: "No se pudo guardar", page: "página", canvas: "lienzo"
    }
  };
  var CV = null, LANG = "en";
  function pick() {
    var c = [(CV && CV.lang && CV.lang()) || document.documentElement.lang || "", navigator.language || ""];
    for (var i = 0; i < c.length; i++) { var k = String(c[i]).toLowerCase().split("-")[0]; if (I18N[k]) return k; }
    return "en";
  }
  function t(k) { return (I18N[LANG] || I18N.en)[k] || I18N.en[k] || k; }

  // ---------- where this artifact is ----------
  var PATH = decodeURIComponent(location.pathname).replace(/^\/+/, "").replace(/index\.html?$/, "");
  var FILE = PATH;                                  // "artifacts/…/x.canvas/" or "artifacts/…/x.html"
  var STATIC = PATH.slice(-1) === "/" ? "comments.json" : PATH.split("/").pop().replace(/\.html?$/, "") + ".comments.json";
  var API = "/api/";
  var live = false, liveView = false, mode = false, showResolved = false, list = [], me = "", lastJson = "";
  var SELF_SRC = document.currentScript && document.currentScript.src;
  // origin: vista en vivo (decisions/0028): live.js se carga solo cuando el visor es `agate.py serve`.
  function loadLive() {
    if (window.__agateLive || document.querySelector("script[data-agate-live]")) return;
    var src = SELF_SRC ? SELF_SRC.replace(/comments\.js(\?.*)?$/, "live.js") : "/.agate/core/canvas/live.js";
    var sc = document.createElement("script");
    sc.src = src; sc.defer = true; sc.setAttribute("data-agate-live", "");
    document.head.appendChild(sc);
  }
  window.AgateComments = { reload: function () { return load(); } };

  // ---------- tiny DOM helpers (text only, never parsed as HTML) ----------
  function el(tag, cls, parent, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    if (parent) parent.appendChild(n);
    return n;
  }
  function when(iso) {
    try { return new Date(iso).toLocaleString(LANG, { dateStyle: "short", timeStyle: "short" }); } catch (e) { return iso || ""; }
  }
  function store(k, v) { try { if (v == null) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }

  function call(route, body) {
    return fetch(API + route, {
      method: "POST", headers: { "Content-Type": "application/json", "X-Agate-Request": "1" },
      body: JSON.stringify(body), credentials: "same-origin"
    }).then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || r.status); return j; }); });
  }
  function load() {
    var url = live ? API + "comments?file=" + encodeURIComponent(FILE) : STATIC;
    return fetch(url, { cache: "no-store" })
      .then(function (r) { return r.ok ? r.text() : '{"comments":[]}'; })
      .then(function (txt) {
        if (txt === lastJson) return;
        lastJson = txt;
        try { list = JSON.parse(txt).comments || []; } catch (e) { list = []; }
        draw();
      })
      .catch(function () { /* offline: keep what we have */ });
  }

  // ---------- styles (self-contained, light/dark) ----------
  function css() {
    var s = el("style", "", document.head);
    s.textContent = [
      ":root{--cm-bg:#fbfbfa;--cm-fg:#1d2126;--cm-mut:#5d636b;--cm-line:#d6d7d4;--cm-acc:#2c5d88;--cm-pin:#a8492a;--cm-soft:#eef2f6}",
      "@media (prefers-color-scheme:dark){:root{--cm-bg:#1c2025;--cm-fg:#e6e8ea;--cm-mut:#9aa1a9;--cm-line:#2f353c;--cm-acc:#7fb0dc;--cm-pin:#e08a66;--cm-soft:#232a33}}",
      ".cm-panel[hidden],.cm-hint[hidden],.cm-pop[hidden]{display:none!important}",
      ".cm-toggle{font:500 13px/1 system-ui,sans-serif;border:1px solid var(--cm-line);background:var(--cm-bg);color:var(--cm-fg);border-radius:6px;padding:7px 10px;cursor:pointer}",
      ".cm-toggle[aria-pressed=true]{background:var(--cm-acc);color:#fff;border-color:var(--cm-acc)}",
      ".cm-float{position:fixed;right:max(16px,env(safe-area-inset-right,0px));bottom:16px;z-index:2147483000;box-shadow:0 4px 16px rgba(0,0,0,.15)}",
      ".cm-layer{position:fixed;inset:0;pointer-events:none;z-index:2147482000}",
      ".cm-pin{position:absolute;pointer-events:auto;transform:translate(-50%,-100%);min-width:24px;height:24px;padding:0 6px;border-radius:12px 12px 12px 2px;border:2px solid #fff;background:var(--cm-pin);color:#fff;font:600 12px/20px system-ui,sans-serif;cursor:pointer;box-shadow:0 2px 6px rgba(0,0,0,.25)}",
      ".cm-pin.cm-done{background:var(--cm-mut);opacity:.75}.cm-pin.cm-hot{outline:3px solid var(--cm-acc)}",
      ".cm-panel{position:fixed;top:0;right:0;bottom:0;width:min(360px,100vw);background:var(--cm-bg);color:var(--cm-fg);border-left:1px solid var(--cm-line);z-index:2147483001;display:flex;flex-direction:column;font:14px/1.45 system-ui,sans-serif;box-shadow:-8px 0 24px rgba(0,0,0,.12)}",
      ".cm-head{display:flex;align-items:center;gap:8px;padding:12px 14px;border-bottom:1px solid var(--cm-line)}.cm-head b{flex:1}",
      ".cm-head button,.cm-thread button,.cm-pop button{font:inherit;font-size:12.5px;border:1px solid var(--cm-line);background:transparent;color:inherit;border-radius:5px;padding:4px 8px;cursor:pointer}",
      ".cm-body{overflow:auto;padding:10px 14px;display:grid;gap:10px}.cm-note{color:var(--cm-mut);font-size:13px}",
      ".cm-note code{background:var(--cm-soft);padding:1px 5px;border-radius:4px;font-size:12px}",
      ".cm-thread{border:1px solid var(--cm-line);border-radius:6px;padding:10px;display:grid;gap:6px;cursor:pointer}.cm-thread.cm-done{opacity:.6}",
      ".cm-meta{font-size:12px;color:var(--cm-mut)}.cm-text{white-space:pre-wrap;overflow-wrap:anywhere}",
      ".cm-reply{border-left:2px solid var(--cm-line);padding-left:8px;display:grid;gap:2px}",
      ".cm-row{display:flex;gap:6px;flex-wrap:wrap}.cm-row input{flex:1;min-width:0;font:inherit;padding:5px 8px;border:1px solid var(--cm-line);border-radius:5px;background:var(--cm-bg);color:inherit}",
      ".cm-pop{position:fixed;z-index:2147483002;width:min(300px,calc(100vw - 32px));background:var(--cm-bg);color:var(--cm-fg);border:1px solid var(--cm-line);border-radius:8px;padding:10px;display:grid;gap:8px;font:14px/1.4 system-ui,sans-serif;box-shadow:0 8px 24px rgba(0,0,0,.2)}",
      ".cm-pop textarea,.cm-pop input{font:inherit;width:100%;box-sizing:border-box;padding:6px 8px;border:1px solid var(--cm-line);border-radius:5px;background:var(--cm-bg);color:inherit}.cm-pop textarea{min-height:80px;resize:vertical}",
      ".cm-hint{position:fixed;left:50%;top:64px;transform:translateX(-50%);z-index:2147483000;background:var(--cm-acc);color:#fff;font:500 13px/1 system-ui,sans-serif;padding:8px 12px;border-radius:6px;pointer-events:none}",
      "body.cm-on,body.cm-on .cv-viewport{cursor:crosshair}"
    ].join("\n");
  }

  // ---------- anchors ----------
  function selectorOf(node) {
    var parts = [];
    while (node && node.nodeType === 1 && node !== document.body && parts.length < 12) {
      if (node.id) { parts.unshift("#" + CSS.escape(node.id)); break; }
      var i = 1, sib = node;
      while ((sib = sib.previousElementSibling)) if (sib.tagName === node.tagName) i++;
      parts.unshift(node.tagName.toLowerCase() + ":nth-of-type(" + i + ")");
      node = node.parentElement;
    }
    return parts.length && parts[0].charAt(0) === "#" ? parts.join(">") : "body>" + parts.join(">");
  }
  function anchorAt(cx, cy, target) {
    if (CV) {
      var b = CV.boardAt(cx, cy);
      if (b) return { kind: "board", board: b.id, rx: b.rx, ry: b.ry, label: b.title };
      var w = CV.toWorld(cx, cy);
      return { kind: "canvas", x: w.x, y: w.y };
    }
    var r = target.getBoundingClientRect();
    var quote = "";
    try { quote = String(window.getSelection() || "").trim().slice(0, 200); } catch (e) { /* none */ }
    var a = { kind: "element", selector: selectorOf(target), rx: r.width ? (cx - r.left) / r.width : 0, ry: r.height ? (cy - r.top) / r.height : 0 };
    var h = target.closest("section,article,h1,h2,h3,h4,figure,table,li");
    if (h) a.label = String((h.querySelector("h1,h2,h3,h4") || h).textContent || "").trim().slice(0, 80);
    if (quote) a.quote = quote;
    return a;
  }
  function screenOf(a) {
    if (!a) return null;
    if (CV) {
      if (a.kind === "board") { var b = CV.board(a.board); if (!b) return null; return CV.toScreen(b.x + a.rx * b.w, b.y + a.ry * b.h); }
      if (a.kind === "canvas") return CV.toScreen(a.x, a.y);
      return null;
    }
    if (a.kind !== "element") return null;
    var n = null;
    try { n = document.querySelector(a.selector); } catch (e) { n = null; }
    if (!n) return null;
    var r = n.getBoundingClientRect();
    return { x: r.left + (a.rx || 0) * r.width, y: r.top + (a.ry || 0) * r.height };
  }
  function anchorText(a) {
    if (!a) return t("page");
    if (a.kind === "board") return a.label || a.board;
    if (a.kind === "canvas") return t("canvas");
    return a.quote ? "«" + a.quote.slice(0, 60) + "»" : (a.label || t("page"));
  }
  function goTo(c) {
    var a = c.anchor || {};
    if (CV) {
      if (a.kind === "board") CV.focusBoard(a.board);
      else if (a.kind === "canvas") CV.focusPoint(a.x, a.y);
    } else if (a.kind === "element") {
      try { var n = document.querySelector(a.selector); if (n) n.scrollIntoView({ block: "center", behavior: "smooth" }); } catch (e) { /* gone */ }
    }
    hot = c.id;
    try { history.replaceState(null, "", "#comment-" + c.id); } catch (e) { /* sandboxed */ }
    setTimeout(place, 350);
  }

  // ---------- UI ----------
  var layer, panel, body, toggle, hint, pop = null, hot = null;
  function draw() { drawPins(); drawPanel(); }
  function drawPins() {
    if (!layer) return;
    while (layer.firstChild) layer.removeChild(layer.firstChild);
    list.forEach(function (c, i) {
      if (c.resolved && !showResolved) return;
      var p = el("button", "cm-pin" + (c.resolved ? " cm-done" : "") + (hot === c.id ? " cm-hot" : ""), layer,
        String(i + 1) + (c.replies && c.replies.length ? " · " + (c.replies.length + 1) : ""));
      p.type = "button";
      p.title = (c.author || "") + ": " + (c.text || "").slice(0, 120);
      p.dataset.id = c.id;
      p.addEventListener("click", function (e) { e.stopPropagation(); openPanel(); hot = c.id; draw(); scrollThread(c.id); });
    });
    place();
  }
  function place() {
    if (!layer) return;
    Array.prototype.forEach.call(layer.children, function (p) {
      var c = list.filter(function (x) { return x.id === p.dataset.id; })[0];
      var s = c && screenOf(c.anchor);
      if (!s || s.x < -40 || s.y < -40 || s.x > innerWidth + 40 || s.y > innerHeight + 40) { p.hidden = true; return; }
      p.hidden = false; p.style.left = s.x + "px"; p.style.top = s.y + "px";
    });
  }
  function scrollThread(id) {
    var n = body && body.querySelector('[data-id="' + id + '"]');
    if (n) n.scrollIntoView({ block: "nearest" });
  }
  function openPanel() { panel.hidden = false; drawPanel(); }
  function drawPanel() {
    if (!panel || panel.hidden) return;
    while (body.firstChild) body.removeChild(body.firstChild);
    if (!live) {
      var ro = el("div", "cm-note", body, t("readonly") + " ");
      el("code", "", ro, "python3 .agate/agate.py serve");
    }
    var shown = list.filter(function (c) { return showResolved || !c.resolved; });
    if (!shown.length) el("div", "cm-note", body, t("none"));
    shown.forEach(function (c) {
      var th = el("div", "cm-thread" + (c.resolved ? " cm-done" : ""), body);
      th.dataset.id = c.id;
      if (hot === c.id) th.style.borderColor = "var(--cm-acc)";
      el("div", "cm-meta", th, (list.indexOf(c) + 1) + " · " + (c.author || "?") + " · " + when(c.created) + " · " + anchorText(c.anchor) + (c.resolved ? " · " + t("resolved") : ""));
      el("div", "cm-text", th, c.text || "");
      (c.replies || []).forEach(function (r) {
        var rp = el("div", "cm-reply", th);
        el("div", "cm-meta", rp, (r.author || "?") + " · " + when(r.created));
        el("div", "cm-text", rp, r.text || "");
      });
      th.addEventListener("click", function (e) { if (!e.target.closest("button,input")) goTo(c); });
      if (!live) return;
      var row = el("div", "cm-row", th);
      var inp = el("input", "", row);
      inp.placeholder = t("replyPh");
      inp.maxLength = 4000;
      var rb = el("button", "", row, t("reply")); rb.type = "button";
      rb.addEventListener("click", function () {
        var txt = inp.value.trim(); if (!txt) return;
        rb.disabled = true;
        withName(function () {
          call("comments/reply", { file: FILE, id: c.id, text: txt, author: me }).then(load)
            .catch(function (err) { alert(t("error") + ": " + err.message); }).then(function () { rb.disabled = false; });
        });
      });
      inp.addEventListener("keydown", function (e) { if (e.key === "Enter") rb.click(); });
      var sb = el("button", "", row, c.resolved ? t("reopen") : t("resolve")); sb.type = "button";
      sb.addEventListener("click", function () {
        call("comments/resolve", { file: FILE, id: c.id, resolved: !c.resolved, author: me }).then(load)
          .catch(function (err) { alert(t("error") + ": " + err.message); });
      });
    });
  }
  function withName(next) {
    if (me) return next();
    var stored = store("agate.author");
    if (stored) { me = stored; return next(); }
    var name = (window.prompt ? window.prompt(t("yourName"), "") : "") || "";
    me = name.trim().slice(0, 80) || "anonymous";
    store("agate.author", me);
    next();
  }
  function closePop() { if (pop) { pop.remove(); pop = null; } }
  function compose(cx, cy, anchor) {
    closePop();
    pop = el("div", "cm-pop", document.body);
    pop.style.left = Math.min(cx + 12, innerWidth - 316) + "px";
    pop.style.top = Math.min(cy + 12, innerHeight - 180) + "px";
    el("div", "cm-meta", pop, anchorText(anchor));
    var ta = el("textarea", "", pop); ta.placeholder = t("placeholder"); ta.maxLength = 4000;
    var row = el("div", "cm-row", pop);
    var ok = el("button", "", row, t("save")); ok.type = "button";
    var no = el("button", "", row, t("cancel")); no.type = "button";
    no.addEventListener("click", closePop);
    ok.addEventListener("click", function () {
      var txt = ta.value.trim(); if (!txt) return;
      ok.disabled = true;
      withName(function () {
        call("comments", { file: FILE, anchor: anchor, text: txt, author: me })
          .then(function (c) { closePop(); hot = c.id; return load(); })
          .catch(function (err) { alert(t("error") + ": " + err.message); ok.disabled = false; });
      });
    });
    ta.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closePop();
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) ok.click();
    });
    setTimeout(function () { ta.focus(); }, 0);
  }
  function setMode(on) {
    mode = !!on && live;
    toggle.setAttribute("aria-pressed", mode ? "true" : "false");
    document.body.classList.toggle("cm-on", mode);
    hint.hidden = !mode;
    if (CV) CV.setClick(mode ? function (cx, cy) { compose(cx, cy, anchorAt(cx, cy)); } : null);
    if (!mode) closePop();
  }
  function onPageClick(e) {
    if (!mode || CV) return;
    if (e.target.closest(".cm-panel,.cm-pop,.cm-toggle,.cm-pin")) return;
    e.preventDefault(); e.stopPropagation();
    compose(e.clientX, e.clientY, anchorAt(e.clientX, e.clientY, e.target));
  }

  function build() {
    LANG = pick();
    css();
    layer = el("div", "cm-layer", document.body);
    panel = el("aside", "cm-panel", document.body);
    panel.hidden = true;
    if (CV) panel.style.top = "64px"; // keep the canvas toolbar (and the Comment button) visible
    var head = el("div", "cm-head", panel);
    el("b", "", head, t("comments"));
    var sr = el("button", "", head, t("showResolved")); sr.type = "button";
    sr.addEventListener("click", function () { showResolved = !showResolved; sr.setAttribute("aria-pressed", String(showResolved)); draw(); });
    var cl = el("button", "", head, t("close")); cl.type = "button";
    cl.addEventListener("click", function () { panel.hidden = true; });
    body = el("div", "cm-body", panel);
    hint = el("div", "cm-hint", document.body, CV ? t("clickHint") : t("pageHint"));
    hint.hidden = true;
    var bar = CV && CV.bar();
    toggle = el("button", "cm-toggle" + (bar ? "" : " cm-float"), bar || document.body, "💬 " + t("comment"));
    toggle.type = "button";
    toggle.title = t("commentTitle");
    toggle.addEventListener("click", function () { openPanel(); setMode(!mode); });
    if (CV) CV.onView(place);
    addEventListener("scroll", place, { passive: true });
    addEventListener("resize", place);
    document.addEventListener("click", onPageClick, true);
    addEventListener("keydown", function (e) {
      if (e.target.closest && e.target.closest("input,textarea,select,[contenteditable]")) return;
      if (e.key === "c" || e.key === "C") { openPanel(); setMode(!mode); }
      else if (e.key === "Escape" && mode) setMode(false);
    });
    var m = /^#comment-(c[0-9a-f]+)$/.exec(location.hash);
    fetch(API + "health", { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; })
      .then(function (h) {
        live = !!(h && h.comments);
        liveView = !!(h && h.live);
        if (!live) toggle.title = t("readonly");
        if (live) fetch(API + "whoami", { cache: "no-store" }).then(function (r) { return r.json(); })
          .then(function (w) { if (w && w.name) me = w.name; }).catch(function () { /* none */ });
        return load();
      })
      .then(function (h) {
        if (m) { var c = list.filter(function (x) { return x.id === m[1]; })[0]; if (c) { openPanel(); goTo(c); } }
        // With the live view (SSE) comments refresh on change; polling stays as a slow fallback.
        if (live) setInterval(function () { if (!window.__agateLiveOn) load(); }, 5000);
        if (liveView) loadLive();
      });
  }

  function init() {
    CV = window.AgateCanvas || null;
    build();
  }
  if (window.AgateCanvas) init();
  else if (document.querySelector("script[src$='canvas.js']") && !window.AgateCanvas) {
    window.addEventListener("agate-canvas-ready", init, { once: true });
  } else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
