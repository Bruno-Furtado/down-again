"use strict";
// Utilitários compartilhados pelo painel e pelo relatório.
const NM = (() => {
  const CAUSES = {
    isp: { label: "Provedor", desc: "o roteador respondia, a internet não", color: "var(--isp)" },
    local: { label: "Rede local / Wi-Fi", desc: "o roteador não respondia ou o monitor perdeu a rede", color: "var(--local)" },
    dns: { label: "DNS / sites", desc: "IPs respondiam, mas os sites não abriam", color: "var(--dns)" },
    unknown: { label: "Indeterminada", desc: "o roteador não responde a ping; não dá para separar", color: "var(--unknown)" },
  };
  const WD = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];
  const pad = (n) => String(n).padStart(2, "0");
  const D = (ts) => new Date(ts * 1000);

  function dur(s) {
    if (s == null) return "—";
    s = Math.round(s);
    if (s < 60) return s + "s";
    const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
    if (d) return `${d}d ${pad(h)}h${pad(m)}`;
    if (h) return `${h}h ${pad(m)}min`;
    return `${m}min ${pad(x)}s`;
  }
  function clock(s) {
    s = Math.max(0, Math.floor(s));
    const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    const c = `${pad(h)}:${pad(m)}:${pad(s % 60)}`;
    return d ? `${d}d ${c}` : c;
  }
  const time = (ts, sec = true) => { const d = D(ts); return `${pad(d.getHours())}:${pad(d.getMinutes())}` + (sec ? `:${pad(d.getSeconds())}` : ""); };
  const date = (ts) => { const d = D(ts); return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()}`; };
  const dayLabel = (ts) => { const d = D(ts); return `${WD[d.getDay()]} ${pad(d.getDate())}/${pad(d.getMonth() + 1)}`; };
  const dt = (ts) => `${dayLabel(ts)} · ${time(ts)}`;
  const dtFull = (ts) => `${date(ts)} ${time(ts)}`;
  const num = (x, n = 0) => (x == null ? "—" : x.toLocaleString("pt-BR", { minimumFractionDigits: n, maximumFractionDigits: n }));
  const pct = (x, n = 2) => (x == null ? "—" : num(x * 100, n) + "%");
  const ms = (v) => (v == null ? "—" : Math.round(v) + " ms");
  const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const cause = (c) => CAUSES[c] || CAUSES.unknown;

  async function get(url, opts) {
    const r = await fetch(url, Object.assign({ cache: "no-store" }, opts));
    if (!r.ok) throw new Error(r.status + "");
    return r.json();
  }

  function rangeFor(key) {
    const t = new Date();
    const from = new Date(t);
    if (key === "7d") from.setDate(t.getDate() - 6);
    if (key === "30d") from.setDate(t.getDate() - 29);
    return { from: iso(from), to: iso(t) };
  }

  function signal(rssi) {
    if (rssi == null) return { bars: 0, label: "" };
    if (rssi >= -55) return { bars: 4, label: "excelente" };
    if (rssi >= -67) return { bars: 3, label: "bom" };
    if (rssi >= -75) return { bars: 2, label: "regular" };
    return { bars: 1, label: "fraco" };
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
      (o.network ? `<br><span class="tip-m">${esc(o.network)}${o.rssi != null ? " · " + Math.round(o.rssi) + " dBm" : ""}</span>` : "") +
      (o.ongoing ? `<br><span class="tip-m">em andamento</span>` : "");
  }

  // Linha do tempo: uma faixa de 24h por dia (mais recente primeiro).
  function timelineHTML(s, { newestFirst = true } = {}) {
    const byStart = {};
    s.outages.forEach((o) => { byStart[o.start] = o; });
    const days = newestFirst ? s.days.slice().reverse() : s.days;
    const ticks = [0, 3, 6, 9, 12, 15, 18, 21, 24].map((h) => `<span style="left:${(h / 24) * 100}%">${h}h</span>`).join("");
    const rows = days.map((d) => {
      const span = d.end - d.start, P = (t) => ((t - d.start) / span) * 100;
      let segs = d.mon.map(([a, b]) => `<i class="s-mon" style="left:${P(a)}%;width:${P(b) - P(a)}%"></i>`).join("");
      if (s.now < d.end) segs += `<i class="s-fut" style="left:${P(Math.max(s.now, d.start))}%;right:0"></i>`;
      segs += d.out.map(([a, b, c]) => {
        const o = Object.values(byStart).find((x) => x.start <= a + 1 && x.end >= b - 1) || { start: a, end: b, dur: b - a, cause: c };
        return `<i class="s-out" data-start="${o.start}" data-tip="${esc(outageTip(o))}" style="left:${P(a)}%;width:${P(b) - P(a)}%;background:${cause(c).color}"></i>`;
      }).join("");
      const av = d.avail == null ? "—" : pct(d.avail, d.avail >= 0.9999 ? 0 : 2);
      return `<div class="tl-row">
        <div class="tl-day">${dayLabel(d.start)}</div>
        <div class="tl-track" data-tip="${esc(`<b>${dayLabel(d.start)}</b><br>${d.count} queda(s) · ${dur(d.down_s)} sem internet<br>monitorado: ${dur(d.mon_s)}`)}">${segs}</div>
        <div class="tl-meta"><b>${d.count}</b> <span>${av}</span></div></div>`;
    }).join("");
    return `<div class="tl"><div class="tl-row tl-axis"><div></div><div class="tl-ticks">${ticks}</div><div class="tl-meta"><span>quedas · disp.</span></div></div>${rows}</div>`;
  }

  function hoursHTML(hours, metric) {
    const val = (h) => (metric === "time" ? h.down_s : h.count);
    const max = Math.max(1, ...hours.map(val));
    const peak = hours.reduce((a, h) => (val(h) > val(a) ? h : a), hours[0]);
    const bars = hours.map((h) => {
      const v = val(h);
      return `<div class="hb${v && h === peak ? " peak" : ""}" data-tip="${esc(`<b>${pad(h.h)}h–${pad((h.h + 1) % 24)}h</b><br>${h.count} queda(s) começaram<br>${dur(h.down_s)} sem internet`)}">
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
      const t = e.touches[0];
      show(el, t.clientX, t.clientY, el.dataset.tip);
    }, { passive: true });
    window.addEventListener("scroll", hide, { passive: true });
    return { show: (x, y, html) => show(null, x, y, html), hide };
  }

  const store = {
    get(k, d) { try { const v = localStorage.getItem("nm_" + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem("nm_" + k, JSON.stringify(v)); } catch (e) { /* sem storage */ } },
  };

  return { CAUSES, cause, dur, clock, time, date, dayLabel, dt, dtFull, num, pct, ms, iso, esc, get, rangeFor,
    signal, wifiIcon, outageTip, timelineHTML, hoursHTML, initTips, store, pad };
})();
