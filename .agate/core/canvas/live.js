/* Agate live view: refresh what changed and show where the AI is editing, with no model tokens.
 *
 * Loaded by comments.js only when the page is served by `agate.py serve` (it answers /api/health with live: true).
 * Listens to /api/events (Server-Sent Events): "changed" comes from the server's file watcher (any harness);
 * "edit" comes from `agate.py serve notify` (e.g. the Claude Code PostToolUse hook) and carries actor + lines.
 * - Canvas (window.AgateCanvas): reloads only the board that changed, re-lays out on canvas.json, refreshes comments,
 *   marks the edited board ("AI editing") and, with "Follow the AI" (F), focuses it. Shows who is viewing.
 * - Any other HTML artifact: reloads keeping the scroll position and shows a small toast.
 */
(function () {
  "use strict";
  if (window.__agateLive || typeof EventSource === "undefined") return;
  window.__agateLive = true;

  var I18N = {
    en: { editing: "editing", ai: "AI", updated: "Updated", follow: "Follow the AI", followTitle: "Follow the AI (F)",
          viewing: "Viewing now", reloaded: "Updated", lines: "lines" },
    es: { editing: "editando", ai: "IA", updated: "Actualizado", follow: "Seguir a la IA", followTitle: "Seguir a la IA (F)",
          viewing: "Viendo ahora", reloaded: "Actualizado", lines: "líneas" }
  };
  var CV = window.AgateCanvas || null;
  function pick() {
    var c = [(CV && CV.lang && CV.lang()) || document.documentElement.lang || "", navigator.language || ""];
    for (var i = 0; i < c.length; i++) { var k = String(c[i]).toLowerCase().split("-")[0]; if (I18N[k]) return k; }
    return "en";
  }
  var LANG = pick();
  function t(k) { return (I18N[LANG] || I18N.en)[k] || I18N.en[k] || k; }
  function store(k, v) { try { if (v == null) return sessionStorage.getItem(k); sessionStorage.setItem(k, v); } catch (e) { return null; } }
  function local(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }

  var PATH = decodeURIComponent(location.pathname).replace(/^\/+/, "").replace(/index\.html?$/, "");
  var FILE = PATH;                                   // "artifacts/…/x.canvas/" or "artifacts/…/x.html"
  var CLIENT = Math.random().toString(36).slice(2, 12);
  var follow = store("agate.live.follow") === "1";
  window.__agateLiveOn = true;

  // ---------- small UI pieces ----------
  var style = document.createElement("style");
  style.textContent =
    ".lv-toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);z-index:2147483000;padding:7px 14px;" +
    "border-radius:999px;background:#e0782e;color:#fff;font:600 13px/1.5 system-ui,sans-serif;box-shadow:0 6px 20px #0003;" +
    "transition:opacity .3s}.lv-toast[hidden]{display:none}" +
    ".lv-viewers{position:fixed;right:14px;bottom:14px;z-index:2147482999;display:flex;gap:2px}" +
    ".lv-viewers span,.cv-viewer{width:24px;height:24px;border-radius:50%;display:inline-grid;place-items:center;" +
    "font:600 11px/1 system-ui,sans-serif;color:#fff;background:#2f6fdb;border:2px solid #fff}";
  document.head.appendChild(style);
  var toast = document.createElement("div");
  toast.className = "lv-toast"; toast.hidden = true; toast.setAttribute("role", "status");
  document.body.appendChild(toast);
  var toastTimer = 0;
  function say(text) {
    toast.textContent = text; toast.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { toast.hidden = true; }, 3500);
  }
  function label(ev) {
    var who = ev.actor || t("ai");
    var txt = ev.type === "edit" ? who + " " + t("editing") : t("updated");
    if (ev.lines) txt += " · " + t("lines") + " " + ev.lines;
    return txt;
  }

  // ---------- canvas ----------
  var timers = {};
  function later(key, fn, ms) { clearTimeout(timers[key]); timers[key] = setTimeout(fn, ms); }
  function onCanvas(ev) {
    var rel = ev.path.slice(FILE.length);
    if (rel === "comments.json") { if (window.AgateComments) window.AgateComments.reload(); return; }
    if (rel === "canvas.json") {
      later("canvas.json", function () {
        fetch("canvas.json", { cache: "no-store" }).then(function (r) { return r.ok ? r.json() : null; })
          .then(function (j) { if (j) CV.relayout(j); }).catch(function () { /* keep the current view */ });
      }, 300);
      return;
    }
    var id = CV.boardForPath(rel);
    if (!id) return;
    if (ev.type === "edit" || !timers["mark:" + id]) CV.mark(id, label(ev));
    timers["mark:" + id] = setTimeout(function () { timers["mark:" + id] = 0; }, 1500);
    later("board:" + id, function () { CV.reloadBoard(id); }, 250);
    if (follow) CV.focusBoard(id);
  }

  // ---------- plain artifact ----------
  var SCROLL_KEY = "agate.live.scroll:" + FILE;
  (function restore() {
    var y = store(SCROLL_KEY);
    if (y != null) { try { sessionStorage.removeItem(SCROLL_KEY); } catch (e) { /* none */ } window.scrollTo(0, +y || 0); }
  })();
  function onPage(ev) {
    if (/\.comments\.json$/.test(ev.path)) { if (window.AgateComments) window.AgateComments.reload(); return; }
    say(label(ev));
    later("page", function () { store(SCROLL_KEY, String(window.scrollY || 0)); location.reload(); }, 400);
  }

  // ---------- events ----------
  var es = new EventSource("/api/events?file=" + encodeURIComponent(FILE));
  es.onmessage = function (m) {
    var ev;
    try { ev = JSON.parse(m.data); } catch (e) { return; }
    if (!ev || typeof ev.path !== "string") return;
    if (CV) onCanvas(ev); else onPage(ev);
  };

  // ---------- follow toggle (canvas) ----------
  if (CV) {
    var bar = CV.bar && CV.bar();
    if (bar) {
      var b = document.createElement("button");
      b.type = "button"; b.className = "cv-live-follow"; b.textContent = "👁 " + t("follow"); b.title = t("followTitle");
      b.setAttribute("aria-pressed", follow ? "true" : "false");
      b.addEventListener("click", function () { setFollow(!follow); });
      bar.insertBefore(b, bar.firstChild);
      var setFollow = function (on) {
        follow = !!on; store("agate.live.follow", follow ? "1" : "0"); b.setAttribute("aria-pressed", follow ? "true" : "false");
      };
      addEventListener("keydown", function (e) {
        if (e.target.closest && e.target.closest("input,textarea,select,[contenteditable]")) return;
        if (e.key === "f" || e.key === "F") setFollow(!follow);
      });
    }
  }

  // ---------- presence ----------
  var box = null;
  function initials(name) {
    var p = String(name || "?").replace(/@.*$/, "").split(/[\s._-]+/).filter(Boolean);
    return ((p[0] || "?")[0] + (p[1] ? p[1][0] : "")).toUpperCase();
  }
  function drawViewers(list) {
    var others = (list || []).filter(function (v) { return v.id !== CLIENT; });
    if (!box) {
      var bar2 = CV && CV.bar && CV.bar();
      box = document.createElement("span");
      box.className = bar2 ? "cv-viewers" : "lv-viewers";
      if (bar2) bar2.insertBefore(box, bar2.firstChild); else document.body.appendChild(box);
    }
    box.textContent = "";
    box.title = t("viewing") + ": " + others.map(function (v) { return v.name || "?"; }).join(", ");
    others.slice(0, 6).forEach(function (v) {
      var s = document.createElement("span");
      if (CV) s.className = "cv-viewer";
      s.textContent = initials(v.name); s.title = v.name || "?";
      box.appendChild(s);
    });
    box.hidden = !others.length;
  }
  function heartbeat() {
    fetch("/api/presence", {
      method: "POST", headers: { "Content-Type": "application/json", "X-Agate-Request": "1" },
      body: JSON.stringify({ file: FILE, id: CLIENT, author: local("agate.author") || "" })
    }).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) { if (j) drawViewers(j.viewers); })
      .catch(function () { /* offline */ });
  }
  heartbeat();
  setInterval(heartbeat, 10000);
})();
