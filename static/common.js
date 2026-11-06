"use strict";
// Utilitários compartilhados pelo painel e pelo relatório (depende de i18n.js).
const NM = (() => {
  const store = {
    get(k, d) { try { const v = localStorage.getItem("nm_" + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem("nm_" + k, JSON.stringify(v)); } catch (e) { /* sem storage */ } },
  };

  /* ---------- idioma ---------- */
  const LANGS = [
    { code: "en", name: "English", locale: "en-US" },
    { code: "pt", name: "Português", locale: "pt-BR" },
    { code: "zh", name: "中文", locale: "zh-CN" },
  ];
  function detectLang() {
    const saved = store.get("lang", null);
    if (saved && I18N[saved]) return saved;
    for (const l of navigator.languages || [navigator.language || "en"]) {
      const code = String(l).slice(0, 2).toLowerCase();
      if (I18N[code]) return code;
    }
    return "en";
  }
  const lang = detectLang();
  const locale = LANGS.find((l) => l.code === lang).locale;
  document.documentElement.lang = locale;

  function t(key, vars) {
    let s = (I18N[lang] && I18N[lang][key]) || I18N.en[key] || key;
    if (vars) for (const k in vars) s = s.split("{" + k + "}").join(vars[k]);
    return s;
  }

  // Bandeiras em SVG: emoji de bandeira não aparece no Windows.
  function star(cx, cy, r, rot) {
    const p = [];
    for (let i = 0; i < 10; i++) {
      const a = rot + (Math.PI / 5) * i - Math.PI / 2, rr = i % 2 ? r * 0.38 : r;
      p.push((cx + rr * Math.cos(a)).toFixed(2) + "," + (cy + rr * Math.sin(a)).toFixed(2));
    }
    return `<polygon points="${p.join(" ")}" fill="#ffde00"/>`;
  }
  const FLAGS = {
    en: () => {
      let s = `<rect width="30" height="20" fill="#fff"/>`;
      for (let i = 0; i < 7; i++) s += `<rect y="${(i * 40) / 13}" width="30" height="${20 / 13}" fill="#b22234"/>`;
      s += `<rect width="13" height="${(20 * 7) / 13}" fill="#3c3b6e"/>`;
      for (let r = 0; r < 4; r++) for (let c = 0; c < 5; c++) s += `<circle cx="${1.5 + c * 2.5}" cy="${1.4 + r * 2.5}" r=".55" fill="#fff"/>`;
      return s;
    },
    pt: () => `<rect width="30" height="20" fill="#009c3b"/><polygon points="15,2.2 27.6,10 15,17.8 2.4,10" fill="#ffdf00"/><circle cx="15" cy="10" r="4.4" fill="#002776"/><path d="M10.8 9.2a9 9 0 0 1 8.5 1.6" stroke="#fff" stroke-width=".8" fill="none"/>`,
    zh: () => `<rect width="30" height="20" fill="#de2910"/>${star(5, 5, 3, 0)}${star(10, 2, 1, 0.9)}${star(12, 4, 1, 0.6)}${star(12, 7, 1, 0)}${star(10, 9, 1, 0.9)}`,
  };
  const flag = (code) => `<svg class="flag" viewBox="0 0 30 20" aria-hidden="true">${FLAGS[code]()}</svg>`;

  // Preenche textos estáticos: data-i18n (texto), data-i18n-html (HTML do próprio dicionário), data-i18n-title.
  function applyStatic(root) {
    (root || document).querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    (root || document).querySelectorAll("[data-i18n-html]").forEach((el) => { el.innerHTML = t(el.dataset.i18nHtml); });
    (root || document).querySelectorAll("[data-i18n-title]").forEach((el) => {
      el.title = t(el.dataset.i18nTitle);
      el.setAttribute("aria-label", el.title);
    });
  }

  // Botão + menu de idioma; trocar recarrega a página (todos os textos e formatos mudam juntos).
  function mountLangMenu(btn, menu) {
    btn.innerHTML = flag(lang);
    btn.title = t("lang");
    btn.setAttribute("aria-label", t("lang"));
    menu.innerHTML = LANGS.map((l) => `<button role="menuitemradio" aria-checked="${l.code === lang}" data-v="${l.code}" class="${l.code === lang ? "on" : ""}">` +
      `${flag(l.code)}<span>${l.name}</span><span>${l.code === lang ? "✓" : ""}</span></button>`).join("");
    const toggle = (open) => { menu.classList.toggle("on", open); btn.setAttribute("aria-expanded", open); };
    btn.addEventListener("click", (e) => { e.stopPropagation(); document.querySelectorAll(".menu.on").forEach((m) => m !== menu && m.classList.remove("on")); toggle(!menu.classList.contains("on")); });
    menu.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      if (b.dataset.v !== lang) { store.set("lang", b.dataset.v); location.reload(); } else toggle(false);
    });
    document.addEventListener("click", () => toggle(false));
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") toggle(false); });
  }

  /* ---------- formatação ---------- */
  const CAUSE_COLORS = { isp: "var(--isp)", local: "var(--local)", dns: "var(--dns)", unknown: "var(--unknown)" };
  const CAUSES = {};
  for (const k in CAUSE_COLORS) CAUSES[k] = { label: t("cause." + k), desc: t("cause." + k + ".desc"), color: CAUSE_COLORS[k] };
  const cause = (c) => CAUSES[c] || CAUSES.unknown;

  const pad = (n) => String(n).padStart(2, "0");
  const D = (ts) => new Date(ts * 1000);
  const U = { d: t("unit.d"), h: t("unit.h"), min: t("unit.min"), s: t("unit.s") };

  function dur(s) {
    if (s == null) return "—";
    s = Math.round(s);
    if (s < 60) return s + U.s;
    const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
    if (d) return `${d}${U.d} ${pad(h)}${U.h}${pad(m)}`;
    if (h) return `${h}${U.h} ${pad(m)}${U.min}`;
    return `${m}${U.min} ${pad(x)}${U.s}`;
  }
  function clock(s) {
    s = Math.max(0, Math.floor(s));
    const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    const c = `${pad(h)}:${pad(m)}:${pad(s % 60)}`;
    return d ? `${d}${U.d} ${c}` : c;
  }
  const fmt = (opts) => new Intl.DateTimeFormat(locale, opts);
  const F_DATE = fmt({ day: "2-digit", month: "2-digit", year: "numeric" });
  const F_DAY = fmt({ weekday: "short", day: "2-digit", month: "2-digit" });
  const F_DAYFULL = fmt({ weekday: "short", day: "2-digit", month: "2-digit", year: "numeric" });
  const time = (ts, sec = true) => { const d = D(ts); return `${pad(d.getHours())}:${pad(d.getMinutes())}` + (sec ? `:${pad(d.getSeconds())}` : ""); };
  const date = (ts) => F_DATE.format(D(ts));
  const dayLabel = (ts) => F_DAY.format(D(ts));
  const dayFull = (ts) => F_DAYFULL.format(D(ts));
  const dt = (ts) => `${dayLabel(ts)} · ${time(ts)}`;
  const dtFull = (ts) => `${date(ts)} ${time(ts)}`;
  const num = (x, n = 0) => (x == null ? "—" : x.toLocaleString(locale, { minimumFractionDigits: n, maximumFractionDigits: n }));
  const pct = (x, n = 2) => (x == null ? "—" : num(x * 100, n) + "%");
  const ms = (v) => (v == null ? "—" : Math.round(v) + " ms");
  const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const endedBy = (code) => (code === "monitor parado" ? t("ended.stopped") : code);

  async function get(url, opts) {
    const r = await fetch(url, Object.assign({ cache: "no-store" }, opts));
    if (!r.ok) throw new Error(r.status + "");
    return r.json();
  }

  function rangeFor(key) {
    const now = new Date();
    const from = new Date(now);
    if (key === "7d") from.setDate(now.getDate() - 6);
    if (key === "30d") from.setDate(now.getDate() - 29);
    return { from: iso(from), to: iso(now) };
  }

  function signal(rssi) {
    if (rssi == null) return { bars: 0, label: "" };
    if (rssi >= -55) return { bars: 4, label: t("sig.excellent") };
    if (rssi >= -67) return { bars: 3, label: t("sig.good") };
    if (rssi >= -75) return { bars: 2, label: t("sig.fair") };
    return { bars: 1, label: t("sig.weak") };
  }

  function wifiIcon(bars, cls = "") {
    const on = (i) => (bars > i ? "on" : "");
    return `<svg class="wifi ${cls}" viewBox="0 0 24 24" aria-hidden="true">
      <path class="${on(3)}" d="M2.5 9.3a13.5 13.5 0 0 1 19 0"/>
      <path class="${on(2)}" d="M5.6 12.6a9.2 9.2 0 0 1 12.8 0"/>
      <path class="${on(1)}" d="M8.7 15.8a4.9 4.9 0 0 1 6.6 0"/>
      <circle class="${on(0)}" cx="12" cy="19.2" r="1.7"/></svg>`;
  }

  function outageTip(o) {
    const c = cause(o.cause);
    return `<b>${esc(c.label)}</b> · ${dur(o.dur)}<br>${dt(o.start)} → ${time(o.end)}` +
      (o.hint ? `<br>${esc(t("hint." + o.hint))}` : "") +
      (o.network ? `<br><span class="tip-m">${esc(o.network)}${o.rssi != null ? " · " + Math.round(o.rssi) + " dBm" : ""}</span>` : "") +
      (o.ongoing ? `<br><span class="tip-m">${t("tip.ongoing")}</span>` : "");
  }

  // Linha do tempo: uma faixa de 24h por dia (mais recente primeiro).
  function timelineHTML(s, { newestFirst = true } = {}) {
    const days = newestFirst ? s.days.slice().reverse() : s.days;
    const ticks = [0, 3, 6, 9, 12, 15, 18, 21, 24].map((h) => `<span style="left:${(h / 24) * 100}%">${h}h</span>`).join("");
    const rows = days.map((d) => {
      const span = d.end - d.start, P = (x) => ((x - d.start) / span) * 100;
      let segs = d.mon.map(([a, b]) => `<i class="s-mon" style="left:${P(a)}%;width:${P(b) - P(a)}%"></i>`).join("");
      if (s.now < d.end) segs += `<i class="s-fut" style="left:${P(Math.max(s.now, d.start))}%;right:0"></i>`;
      segs += d.out.map(([a, b, c]) => {
        const o = s.outages.find((x) => x.start <= a + 1 && x.end >= b - 1) || { start: a, end: b, dur: b - a, cause: c };
        return `<i class="s-out" data-start="${o.start}" data-tip="${esc(outageTip(o))}" style="left:${P(a)}%;width:${P(b) - P(a)}%;background:${cause(c).color}"></i>`;
      }).join("");
      // instabilidade: faixa fina embaixo (a conexão não caiu, mas falhou ou ficou lenta)
      segs += (d.uns || []).map(([a, b]) => {
        const ev = (s.events || []).find((x) => x.kind === "unstable" && x.start <= a + 1 && x.end >= b - 1) || { start: a, end: b, data: {} };
        const tip = `<b>${esc(t("ev.unstableTag"))}</b> · ${dur(ev.end - ev.start)}<br>${dt(ev.start)} → ${time(ev.end)}`;
        return `<i class="s-uns" data-start="${ev.start}" data-tip="${esc(tip)}" style="left:${P(a)}%;width:${P(b) - P(a)}%"></i>`;
      }).join("");
      const av = d.avail == null ? "—" : pct(d.avail, d.avail >= 0.9999 ? 0 : 2);
      const tip = t("tl.tip", { day: esc(dayLabel(d.start)), n: d.count, down: dur(d.down_s), mon: dur(d.mon_s) });
      return `<div class="tl-row">
        <div class="tl-day">${esc(dayLabel(d.start))}</div>
        <div class="tl-track" data-tip="${esc(tip)}">${segs}</div>
        <div class="tl-meta"><b>${d.count}</b> <span>${av}</span></div></div>`;
    }).join("");
    return `<div class="tl"><div class="tl-row tl-axis"><div></div><div class="tl-ticks">${ticks}</div><div class="tl-meta"><span>${t("tl.header")}</span></div></div>${rows}</div>`;
  }

  function hoursHTML(hours, metric) {
    const val = (h) => (metric === "time" ? h.down_s : h.count);
    const max = Math.max(1, ...hours.map(val));
    const peak = hours.reduce((a, h) => (val(h) > val(a) ? h : a), hours[0]);
    const bars = hours.map((h) => {
      const v = val(h);
      const tip = t("hours.tip", { range: `${pad(h.h)}h–${pad((h.h + 1) % 24)}h`, n: h.count, down: dur(h.down_s) });
      return `<div class="hb${v && h === peak ? " peak" : ""}" data-tip="${esc(tip)}">
        <i style="height:${v ? Math.max(4, (v / max) * 100) : 0}%"></i><span>${h.h % 3 === 0 ? h.h + "h" : ""}</span></div>`;
    }).join("");
    return `<div class="hbars">${bars}</div>`;
  }

  // Tooltip único para qualquer elemento com data-tip (mouse e toque).
  function initTips() {
    const tip = document.createElement("div");
    tip.id = "tip";
    document.body.appendChild(tip);
    let cur = null;
    const place = (x, y) => {
      const r = tip.getBoundingClientRect();
      let left = x + 14, top = y + 16;
      if (left + r.width > window.innerWidth - 8) left = x - r.width - 14;
      if (top + r.height > window.innerHeight - 8) top = y - r.height - 12;
      tip.style.transform = `translate(${Math.max(8, left)}px, ${Math.max(8, top)}px)`;
    };
    const show = (el, x, y, html) => { cur = el; tip.innerHTML = html; tip.classList.add("on"); place(x, y); };
    const hide = () => { cur = null; tip.classList.remove("on"); };
    document.addEventListener("mousemove", (e) => {
      const el = e.target.closest && e.target.closest("[data-tip]");
      if (!el) return cur && hide();
      if (el !== cur) show(el, e.clientX, e.clientY, el.dataset.tip); else place(e.clientX, e.clientY);
    });
    document.addEventListener("touchstart", (e) => {
      const el = e.target.closest && e.target.closest("[data-tip]");
      if (!el) return hide();
      const tt = e.touches[0];
      show(el, tt.clientX, tt.clientY, el.dataset.tip);
    }, { passive: true });
    window.addEventListener("scroll", hide, { passive: true });
    return { show: (x, y, html) => show(null, x, y, html), hide };
  }

  return { lang, locale, LANGS, t, flag, applyStatic, mountLangMenu, CAUSES, cause, dur, clock, time, date, dayLabel, dayFull,
    dt, dtFull, num, pct, ms, iso, esc, endedBy, get, rangeFor, signal, wifiIcon, outageTip, timelineHTML, hoursHTML,
    initTips, store, pad };
})();
