"use strict";
const $ = (s) => document.querySelector(s);
const { esc, dur, cause, CAUSES, t } = NM;
const tips = NM.initTips();
NM.applyStatic();

const S = {
  cfg: null, st: null, gl: null, sum: null, series: null, speed: null, offset: 0, failCount: 0,
  tab: "now", period: NM.store.get("period", "7d"), custom: NM.store.get("custom", null),
  seriesH: NM.store.get("series", "6"), hourMetric: "count", filter: "all", sort: "recent", limit: 40,
};
const nowS = () => Date.now() / 1000 + S.offset;
// Só mexe no DOM quando o texto muda: o painel fica aberto o dia todo (CPU e bateria).
const setText = (el, v) => { if (el.textContent !== v) el.textContent = v; };
const setHTML = (el, v) => { if (el._html !== v) { el.innerHTML = v; el._html = v; } };
const setClass = (el, v) => { if (el.className !== v) el.className = v; };
const mbps = (v) => (v == null ? "—" : `${NM.num(v, v < 10 ? 1 : 0)} Mbps`);
// "há X" com resolução de minutos
const ago = (sec) => (sec < 60 ? `< 1 ${t("unit.min")}` : sec < 3600 ? `${Math.round(sec / 60)} ${t("unit.min")}` : dur(Math.round(sec / 60) * 60));
const planNow = () => ({ down: Number((S.cfg && S.cfg.plan_down_mbps) || 0), up: Number((S.cfg && S.cfg.plan_up_mbps) || 0) });

/* ---------- abas ---------- */
const TABS = ["now", "history", "report", "settings"];
function showTab(tab) {
  if (!TABS.includes(tab)) tab = "now";
  S.tab = tab;
  TABS.forEach((x) => { $("#v-" + x).hidden = x !== tab; });
  document.querySelectorAll("#tabs a").forEach((a) => {
    const on = a.dataset.tab === tab;
    a.classList.toggle("on", on);
    a.setAttribute("aria-selected", on);
  });
  // o mesmo seletor de período serve ao histórico e ao relatório
  (tab === "report" ? $("#rep-period-slot") : $("#hist-period-slot")).appendChild($("#period"));
  if (tab === "now") { renderSeries(); loadSeries(); renderSpeedMini(); loadSpeedRecent(); }
  if (tab === "history" || tab === "report") { renderSummary(); renderSpeedChart(); loadSummary(); }
  if (tab === "settings") loadConfig();
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", () => showTab(location.hash.slice(1)));

/* ---------- tema ---------- */
const DARK_FROM = 18, DARK_TO = 6;   // "pelo horário": escuro das 18h às 6h
const THEMES = [["hour", t("theme.hour")], ["system", t("theme.system")], ["light", t("theme.light")], ["dark", t("theme.dark")]];
let theme = NM.store.get("tema", "hour");

function applyTheme() {
  let th = theme;
  if (th === "hour") { const h = new Date().getHours(); th = h >= DARK_FROM || h < DARK_TO ? "dark" : "light"; }
  if (th === "system") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = th;
  const shown = th === "system" ? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light") : th;
  document.querySelector('meta[name="theme-color"]').content = shown === "dark" ? "#0b0b0e" : "#f2f3f6";
  $("#theme-seg").innerHTML = THEMES.map(([k, l]) => `<button data-v="${k}" class="${k === theme ? "on" : ""}">${l}</button>`).join("");
  $("#theme-hint").textContent = theme === "hour" ? t("theme.hourHint", { a: DARK_FROM, b: DARK_TO }) : theme === "system" ? t("theme.systemHint") : "";
}
$("#theme-seg").onclick = (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  theme = b.dataset.v; NM.store.set("tema", theme); applyTheme();
};
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyTheme);
applyTheme();
setInterval(applyTheme, 60000);

/* ---------- idioma do painel ---------- */
$("#lang-seg").innerHTML = NM.LANGS.map((l) => `<button data-v="${l.code}" class="${l.code === NM.lang ? "on" : ""}">${NM.flag(l.code)}<span>${l.name}</span></button>`).join("");
$("#lang-seg").onclick = (e) => {
  const b = e.target.closest("button");
  if (b && b.dataset.v !== NM.lang) { NM.store.set("lang", b.dataset.v); location.reload(); }
};

/* ---------- segmentados ---------- */
function seg(el, value, onPick) {
  const set = (v) => el.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.v === v));
  set(value);
  el.onclick = (e) => { const b = e.target.closest("button"); if (!b) return; set(b.dataset.v); onPick(b.dataset.v); };
}

/* ---------- aviso rápido (salvo, erro) ---------- */
const toastEl = document.createElement("div");
toastEl.id = "toast";
document.body.appendChild(toastEl);
let toastT;
function toast(msg, ok = true) {
  toastEl.textContent = msg;
  toastEl.className = "on " + (ok ? "ok" : "bad");
  clearTimeout(toastT);
  toastT = setTimeout(() => { toastEl.className = ""; }, 2200);
}

/* ---------- status ao vivo ---------- */
function favicon(color) {
  $("#favicon").href = "data:image/svg+xml," + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6.5" fill="${color}"/></svg>`);
}

function heroState() {
  const st = S.st;
  if (!st) return { cls: "idle", title: t("noContact"), lbl: "", big: "", sub: t("hero.noContact.sub") };
  const now = nowS();
  if (st.last && now - st.last > Math.max(30, st.interval * 5))
    return { cls: "idle", title: t("hero.stopped"), lbl: t("hero.lastCheck"), big: NM.time(st.last), sub: t("hero.stopped.sub") };
  if (st.state === "starting") return { cls: "idle", title: t("hero.starting"), lbl: "", big: "", sub: t("hero.starting.sub") };
  if (st.state === "down") {
    return { cls: "down", title: t("hero.down"), lbl: t("hero.downFor"), big: NM.clock(now - st.outage.start),
      sub: t("hero.down.sub", { time: NM.time(st.outage.start), cause: esc(cause(st.outage.cause).label) }) };
  }
  if (st.pending) return { cls: "warn", title: t("hero.checking"), lbl: t("hero.onlineFor"), big: NM.clock(now - st.since),
    sub: t("hero.checking.sub", { n: st.pending }) };
  const u = st.unstable;
  if (u) return { cls: "warn", title: t("hero.unstable"), lbl: t("hero.unstableFor"), big: NM.clock(now - u.start),
    sub: t("hero.unstable.sub", { loss: NM.pct(u.n ? u.loss / u.n : 0, 0), max: NM.ms(u.max_ms) }) };
  return { cls: "up", title: t("hero.online"), lbl: st.since_start ? t("hero.monitoringFor") : t("hero.noOutagesFor"), big: NM.clock(now - st.since),
    sub: esc(st.since_start ? t("hero.sinceStart", { dt: NM.dt(st.since) }) : t("hero.lastEnded", { dt: NM.dt(st.since) })) };
}

// Disponibilidade das últimas 24h com as casas decimais menores, como o saldo num app de banco.
function availHTML(av) {
  const n = av >= 1 ? 0 : av >= 0.9995 ? 2 : 1;
  const m = NM.num(av * 100, n).match(/^(\d+)(\D\d+)?$/);
  return m ? `${m[1]}<span class="dec">${m[2] || ""}%</span>` : esc(NM.pct(av, n));
}

// Topo: com a internet no ar o número grande é a disponibilidade de 24h; na queda, o tempo fora.
function renderHero() {
  const h = heroState();
  if (renderHero.cls !== h.cls) {
    $("#status").className = "hero is-" + h.cls;
    document.body.dataset.state = h.cls;
    favicon({ up: "#12b76a", down: "#f04438", warn: "#f79009", idle: "#98a2b3" }[h.cls]);
    renderHero.cls = h.cls;
  }
  const av = S.avail24, ok = (h.cls === "up" || h.cls === "warn") && av != null;
  setText($("#st-title"), h.title);
  setText($("#st-lbl"), ok ? t("hero.avail24") : h.lbl);
  setHTML($("#st-num"), ok ? availHTML(av) : esc(h.big));
  setHTML($("#st-sub"), ok ? `${esc(h.lbl)} <b>${esc(h.big)}</b>` + (h.cls === "warn" ? `<br>${h.sub}` : "") : h.sub);
  const title = (h.cls === "down" ? t("title.down", { t: h.big }) : h.title) + " · down-again";
  if (document.title !== title) document.title = title;
}

function setNode(id, cls, text) { const n = $(id); setClass(n, "node " + cls); setText(n.querySelector("small"), text); }
function setLink(id, cls) { setClass($(id), "link " + cls); }

function renderPath() {
  const st = S.st, p = st && st.probe, net = st && st.net;
  if (!p) { ["#n-pc", "#n-gw", "#n-net", "#n-web"].forEach((n) => setNode(n, "idle", "—")); ["#l-1", "#l-2", "#l-3"].forEach((l) => setLink(l, "idle")); return; }
  const hasNet = net && net.kind;
  const sig = NM.signal(net && net.rssi);
  setNode("#n-pc", hasNet ? "ok" : "bad", !hasNet ? t("path.noNetwork") : net.kind === "cabo" ? t("path.cable") : (net.ssid || "Wi-Fi") + (sig.label ? ` · ${sig.label}` : ""));
  const gwOk = p.gw && p.gw_ms != null, gwState = !p.gw ? "bad" : gwOk ? "ok" : p.state === "local" ? "bad" : "unk";
  setLink("#l-1", gwState);
  setNode("#n-gw", gwState, !p.gw ? t("path.unreachable") : gwOk ? NM.ms(p.gw_ms) : gwState === "unk" ? t("path.noPing") : t("path.noReply"));
  const netOk = p.net_ms != null;
  setLink("#l-2", netOk ? "ok" : gwState === "bad" ? "idle" : "bad");
  setNode("#n-net", netOk ? "ok" : gwState === "bad" ? "idle" : "bad", netOk ? NM.ms(p.net_ms) : t("path.noReply"));
  setLink("#l-3", !netOk ? "idle" : p.http_ok ? "ok" : "bad");
  setNode("#n-web", !netOk ? "idle" : p.http_ok ? "ok" : "bad", !netOk ? "—" : p.http_ok ? t("path.loading") : t("path.notLoading"));
  setText($("#path-note"), p.state === "ok" ? t("note.ok", { n: st.interval }) : t("note." + p.state));
  const ip = st.public_ip;
  setText($("#path-ip"), ip ? t("path.publicIp", { ip: ip.ip, d: ago(nowS() - ip.since) }) : "");
}

function renderNet() {
  const net = S.st && S.st.net, chip = $("#netchip");
  const tip = (v) => { if (chip.dataset.tip !== v) chip.dataset.tip = v; };
  if (!net || !net.kind) {
    tip(t("net.tip"));
    setHTML($("#neticon"), NM.wifiIcon(4, "off")); setText($("#netname"), t("net.none")); setText($("#netsub"), ""); return;
  }
  if (net.kind === "cabo") {
    setHTML($("#neticon"), `<svg class="wifi" viewBox="0 0 24 24"><path class="on" d="M9 3v4M15 3v4M7 7h10v5a5 5 0 0 1-10 0zM12 17v4"/></svg>`);
    setText($("#netname"), t("net.cable"));
    setText($("#netsub"), net.port || net.iface || "");
    // dataset recebe HTML pronto (não passa pelo parser): escapa só os valores vindos do sistema
    tip(`<b>${t("net.cableTip")}</b><br>${esc(net.port || "")} (${esc(net.iface || "")})`);
    return;
  }
  const sig = NM.signal(net.rssi);
  setHTML($("#neticon"), NM.wifiIcon(net.rssi == null ? 4 : sig.bars));   // sem leitura de sinal: ícone cheio
  setText($("#netname"), net.ssid || "Wi-Fi");
  setText($("#netsub"), net.rssi != null ? `${Math.round(net.rssi)} dBm · ${sig.label}` : "");
  tip(`<b>${esc(net.ssid || "Wi-Fi")}</b><br>` +
    [net.rssi != null && t("net.signal", { v: `${Math.round(net.rssi)} dBm (${sig.label})` }),
     net.noise != null && t("net.noise", { v: `${Math.round(net.noise)} dBm` }),
     net.channel && t("net.channel", { v: esc(net.channel) }),
     net.tx_rate && t("net.link", { v: Math.round(net.tx_rate) })].filter(Boolean).join("<br>"));
}

async function pollStatus() {
  try {
    const st = await NM.get("/api/status");
    S.offset = st.now - Date.now() / 1000;
    const key = (x) => x && [x.state, x.outage && x.outage.start, x.unstable && x.unstable.start, x.public_ip && x.public_ip.ip].join("|");
    const changed = !S.st || key(S.st) !== key(st);
    const lastSpeed = (x) => (x && x.speed && x.speed.last ? x.speed.last.ts : null);
    const newSpeed = S.st && lastSpeed(st) !== lastSpeed(S.st);
    S.st = st; S.failCount = 0;
    renderPath(); renderNet(); renderSpeedNow();
    if (newSpeed) { loadSpeedRecent(); if (S.tab === "history") loadSpeed(); }
    if (changed) { loadGlance(); if (S.tab === "now") loadSeries(); else if (S.tab !== "settings") loadSummary(); }
  } catch (e) {
    if (++S.failCount >= 2) { S.st = null; renderPath(); }
  }
  renderHero();
}

/* ---------- últimas 24h e acontecimentos recentes ---------- */
async function loadGlance() {
  try { S.gl = await NM.get("/api/glance"); renderGlance(); renderRecent(); } catch (e) { /* tenta no próximo ciclo */ }
}

// Faixa das últimas 24h dentro do status: verde = monitorado, cores = quedas, amarelo embaixo = instável.
function renderGlance() {
  const g = S.gl;
  if (!g) return;
  const h = g.h24, span = g.now - g.from, P = (x) => (((x - g.from) / span) * 100).toFixed(3);
  const sum = [!h.count ? t("gl.none") : h.count === 1 ? t("gl.one") : t("gl.many", { n: h.count })];
  if (h.count) sum.push(t("gl.offline", { d: dur(h.down_s) }));
  if (h.unstable) sum.push(h.unstable === 1 ? t("gl.unstableOne") : t("gl.unstableMany", { n: h.unstable }));
  setText($("#day-sum"), sum.join(" · "));
  const monS = g.mon.reduce((a, [x, y]) => a + (y - x), 0);
  S.avail24 = monS > 0 ? Math.max(0, Math.min(1, 1 - h.down_s / monS)) : null;
  renderHero();
  const seg = (cls, a, b, extra) => `<i class="${cls}" style="left:${P(a)}%;width:${P(b) - P(a)}%${extra || ""}"`;
  const tip = (label, a, b) => esc(`<b>${esc(label)}</b> · ${dur(b - a)}<br>${NM.time(a)} → ${NM.time(b)}`);
  setHTML($("#day-track"), g.mon.map(([a, b]) => seg("s-mon", a, b) + "></i>").join("") +
    g.uns.map(([a, b]) => seg("s-uns", a, b) + ` data-tip="${tip(t("ev.unstableTag"), a, b)}"></i>`).join("") +
    g.out.map(([a, b, c]) => seg("s-out", a, b, `;background:${cause(c).color}`) + ` data-tip="${tip(cause(c).label, a, b)}"></i>`).join(""));
  setHTML($("#day-ticks"), [0, 1, 2, 3, 4].map((i) => `<span>${i === 4 ? t("gl.now") : NM.time(g.from + (span / 4) * i, false)}</span>`).join(""));
}
$("#day").onclick = () => { location.hash = "history"; };

// Uma linha por acontecimento: queda, instabilidade ou troca de IP público.
function eventRow(x, maxDur) {
  const when = x.ongoing ? t("list.until", { t: t("list.now") }) : t("list.until", { t: NM.time(x.end) });
  if (x.kind === "outage") {
    const c = cause(x.cause), sig = NM.signal(x.rssi);
    const notes = [x.hint && t("hint." + x.hint), x.ended_by && x.ended_by !== "voltou" && NM.endedBy(x.ended_by),
      x.network && x.network + (x.rssi != null ? ` · ${Math.round(x.rssi)} dBm (${sig.label})` : "")].filter(Boolean);
    return row(c.color, x.start, t("ev.outage", { d: dur(x.dur) }), c.label, `${esc(NM.dt(x.start))} ${when}`, notes, x.ongoing, x.dur, maxDur);
  }
  if (x.kind === "unstable") {
    const d = x.data || {};
    const detail = d.n ? t("ev.unstableDetail", { loss: NM.pct(d.loss / d.n, 0), max: NM.ms(d.max_ms) }) : "";
    return row("var(--unst)", x.start, t("ev.unstable", { d: dur(x.dur) }), t("ev.unstableTag"), `${esc(NM.dt(x.start))} ${when}`, [detail], x.ongoing, x.dur, maxDur);
  }
  const d = x.data || {};
  const why = d.silent ? t("ev.ipSilent") : d.late ? t("ev.ipLate") : d.hint ? t("hint." + d.hint) : "";
  return row("var(--accent)", x.end, t("ev.ip"), t("ev.ipTag"), esc(NM.dt(x.end)), [`${d.old || "?"} → ${d.new || "?"}`, why], false, 0, maxDur);
}

function row(color, start, title, tag, when, notes, live, d, maxDur) {
  return `<div class="ev" data-start="${start}" style="--c:${color}"><i class="ev-dot"></i>
    <div class="ev-main"><b>${esc(title)}</b>${live ? `<span class="live">${t("list.live")}</span>` : ""}<small>${when}</small></div>
    <div class="ev-tag"><span>${esc(tag)}</span>${maxDur && d ? `<u style="width:${Math.max(4, (d / maxDur) * 100)}%"></u>` : ""}</div>
    <div class="ev-notes">${notes.filter(Boolean).map((n) => `<small>${esc(n)}</small>`).join("")}</div></div>`;
}

const TX_ICON = {
  outage: '<path d="M2 8.5a15 15 0 0 1 20 0M5.5 12a10 10 0 0 1 13 0M9 15.5a5 5 0 0 1 6 0"/><path d="M3 3l18 18"/>',
  unstable: '<path d="M2 12h3l2.5-6 4 12 3-9 2 3H22"/>',
  ip_change: '<path d="M4 8h14l-3-3M20 16H6l3 3"/>',
};

// Aba Agora: os acontecimentos como o extrato de um banco (dia, ícone, nome, valor à direita).
function txRow(x) {
  const end = x.ongoing ? t("list.now") : NM.time(x.end, false);
  let color, title, sub, amount;
  if (x.kind === "outage") {
    const c = cause(x.cause);
    color = c.color; title = t("ev.outageTag"); amount = dur(x.dur);
    sub = `${c.label} · ${NM.time(x.start, false)} → ${end}` + (x.hint ? ` · ${t("hint." + x.hint)}` : "");
  } else if (x.kind === "unstable") {
    const d = x.data || {};
    color = "var(--unst)"; title = t("ev.unstableTag"); amount = dur(x.dur);
    sub = `${NM.time(x.start, false)} → ${end}` + (d.n ? ` · ${t("ev.unstableDetail", { loss: NM.pct(d.loss / d.n, 0), max: NM.ms(d.max_ms) })}` : "");
  } else {
    const d = x.data || {};
    color = "var(--accent)"; title = t("ev.ip"); amount = NM.time(x.end, false);
    sub = `${d.old || "?"} → ${d.new || "?"}`;
  }
  return `<div class="tx-row" style="--c:${color}"><span class="tx-ic"><svg viewBox="0 0 24 24">${TX_ICON[x.kind] || TX_ICON.ip_change}</svg></span>
    <div class="tx-main"><b>${esc(title)}</b><small>${esc(sub)}</small></div>
    <div class="tx-amt"><b>${esc(amount)}</b>${x.ongoing ? `<span class="live">${t("list.live")}</span>` : ""}</div></div>`;
}

function dayName(ts) {
  const d = new Date(ts * 1000), today = new Date(nowS() * 1000);
  const diff = Math.round((new Date(today.getFullYear(), today.getMonth(), today.getDate()) - new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 86400000);
  return diff === 0 ? t("day.today") : diff === 1 ? t("day.yesterday") : NM.dayLabel(ts);
}

function renderRecent() {
  const items = ((S.gl && S.gl.recent) || []).slice(0, 7);
  if (!items.length) { setHTML($("#recent"), `<div class="empty">${t("recent.none")}</div>`); return; }
  let html = "", last = null;
  for (const x of items) {
    const day = dayName(x.kind === "ip_change" ? x.end : x.start);
    if (day !== last) { html += `<div class="tx-day">${esc(day)}</div>`; last = day; }
    html += txRow(x);
  }
  setHTML($("#recent"), html);
}

/* ---------- gráfico de latência ---------- */
async function loadSeries() {
  try { S.series = await NM.get("/api/timeseries?hours=" + S.seriesH); renderSeries(); } catch (e) { /* tenta no próximo ciclo */ }
}

function niceMax(v) {
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

function axes(W, H, L, R, T, B, yMax, Y, n = 4) {
  let g = "";
  for (let i = 0; i <= n; i++) {
    const v = (yMax / n) * i, y = Y(v);
    g += `<line class="gl" x1="${L}" x2="${W - R}" y1="${y}" y2="${y}"/><text class="ax" x="${L - 6}" y="${y + 3.5}" text-anchor="end">${Math.round(v)}</text>`;
  }
  return g;
}

function renderSeries() {
  const box = $("#chart"), d = S.series;
  if (!d || S.tab !== "now") return;
  const W = box.clientWidth, H = box.clientHeight, L = 38, R = 6, T = 8, B = 22;
  if (W < 120) return void setTimeout(renderSeries, 300);   // ainda sem layout: tenta de novo
  const pts = d.points, span = d.now - d.from;
  const X = (x) => L + ((x - d.from) / span) * (W - L - R);
  const vals = pts.map((p) => p.max).filter((v) => v != null).sort((a, b) => a - b);
  const cap = vals.length ? vals[Math.floor(vals.length * 0.98)] : 50;
  const yMax = niceMax(Math.max(20, cap * 1.1));
  const Y = (v) => T + (1 - Math.min(v, yMax) / yMax) * (H - T - B);
  const bw = Math.max(1.5, (d.step / span) * (W - L - R));
  let g = axes(W, H, L, R, T, B, yMax, Y);
  const nT = W < 500 ? 3 : 6;
  for (let i = 0; i <= nT; i++) {
    const x = d.from + (span / nT) * i;
    const lbl = span > 2 * 86400 ? NM.dayLabel(x) : NM.time(x, false);
    g += `<text class="ax" x="${X(x)}" y="${H - 5}" text-anchor="${i === 0 ? "start" : i === nT ? "end" : "middle"}">${esc(lbl)}</text>`;
  }
  const fails = pts.filter((p) => p.fail > 0).map((p) =>
    `<rect class="fail" x="${X(p.t)}" y="${T}" width="${bw}" height="${H - T - B}" opacity="${0.12 + 0.5 * (p.fail / p.n)}"/>`).join("");
  const line = (key) => {
    let s = "", prev = null;
    pts.forEach((p) => {
      if (p[key] == null) { prev = null; return; }
      s += (prev == null || p.t - prev > d.step * 1.6 ? "M" : "L") + X(p.t + d.step / 2).toFixed(1) + " " + Y(p[key]).toFixed(1);
      prev = p.t;
    });
    return s;
  };
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}">${g}${fails}<path class="l-gw" d="${line("gw")}"/><path class="l-avg" d="${line("avg")}"/>
    <line class="xh" id="xh" y1="${T}" y2="${H - B}"/><circle class="dot" id="xd" r="4.5"/>
    <rect id="ov" x="${L}" y="0" width="${W - L - R}" height="${H}" fill="transparent"/></svg>`;
  if (!pts.length) box.insertAdjacentHTML("beforeend", `<div class="empty chart-empty"><span>${t("chart.empty")}</span></div>`);
  const ov = box.querySelector("#ov"), xh = box.querySelector("#xh"), xd = box.querySelector("#xd");
  const move = (cx, cy) => {
    if (!pts.length) return;
    const r = box.getBoundingClientRect(), x = cx - r.left;
    const at = d.from + ((x - L) / (W - L - R)) * span;
    let best = pts[0];
    for (const p of pts) if (Math.abs(p.t - at) < Math.abs(best.t - at)) best = p;
    const px = X(best.t + d.step / 2);
    xh.setAttribute("x1", px); xh.setAttribute("x2", px);
    xd.setAttribute("cx", px); xd.setAttribute("cy", best.avg != null ? Y(best.avg) : Y(0));
    box.classList.add("hover");
    const sig = NM.signal(best.rssi);
    tips.show(cx, cy, `<b>${esc(span > 86400 ? NM.dt(best.t) : NM.time(best.t, false))}</b>` +
      `<br>${t("chart.internet", { v: NM.ms(best.avg) })}` +
      `<br>${t("chart.router", { v: NM.ms(best.gw) })}` +
      (best.fail ? `<br><span style="color:#ff8a80">${t("chart.fails", { f: best.fail, n: best.n })}</span>` : "") +
      (best.rssi != null ? `<br><span class="tip-m">${t("chart.signal", { v: Math.round(best.rssi) + " dBm", label: sig.label })}</span>` : ""));
  };
  ov.addEventListener("mousemove", (e) => move(e.clientX, e.clientY));
  ov.addEventListener("touchmove", (e) => { move(e.touches[0].clientX, e.touches[0].clientY); }, { passive: true });
  ov.addEventListener("touchstart", (e) => { move(e.touches[0].clientX, e.touches[0].clientY); }, { passive: true });
  ov.addEventListener("mouseleave", () => { box.classList.remove("hover"); tips.hide(); });
}

/* ---------- velocidade agora ---------- */
function speedRow(label, value, plan, color) {
  const pct = plan && value != null ? value / plan : null;
  return `<div class="sp-tile" style="--c:${color}"><span class="sp-lbl">${label}</span>` +
    `<div class="sp-val"><b>${value == null ? "—" : NM.num(value, value < 10 ? 1 : 0)}</b><small>Mbps</small></div>` +
    `<div class="sp-bar"><i style="width:${pct != null ? Math.min(100, pct * 100) : value != null ? 100 : 0}%"></i></div>` +
    (pct != null ? `<span class="sp-pct${pct < 0.4 ? " low" : ""}">${t("speed.ofPlan", { p: NM.pct(pct, 0) })}</span>` : "") + `</div>`;
}

function renderSpeedNow() {
  const sp = S.st && S.st.speed, plan = planNow(), now = nowS();
  let html = "";
  if (sp) {
    const l = sp.last;
    if (!l) html = `<p class="sp-meta">${t(sp.enabled ? "speed.none" : "speed.off")}</p>`;
    else if (l.error) html = `<p class="sp-meta">${esc(t("speed.failedLast", { e: l.error }))}</p>`;
    else {
      html = `<div class="sp-tiles">${speedRow("↓ " + t("speed.download"), l.down, plan.down, "var(--accent)") + speedRow("↑ " + t("speed.upload"), l.up, plan.up, "var(--ok)")}</div>` +
        `<p class="sp-meta">${t("speed.ping", { p: NM.ms(l.ping), j: NM.ms(l.jitter) })}</p>`;
    }
    if (!plan.down && S.cfg) html += `<p class="sp-meta"><a href="#settings">${t("speed.setPlan")}</a></p>`;
    setText($("#speed-when"), sp.running ? t("speed.running") : [l && t("speed.last", { d: ago(now - l.ts) }),
      sp.enabled ? sp.next && t("speed.next", { d: ago(Math.max(0, sp.next - now)) }) : t("speed.off")].filter(Boolean).join(" · "));
  }
  setHTML($("#speed-vals"), html);
  const busy = !!(sp && sp.running), btn = $("#speed-run");
  if (btn.disabled !== busy) { btn.classList.toggle("busy", busy); btn.disabled = busy; $("#act-speed").classList.toggle("busy", busy); $("#act-speed").disabled = busy; }
}

$("#speed-run").onclick = async () => {
  const res = $("#speed-res");
  res.className = "res"; res.textContent = "";
  try {
    const r = await (await fetch("/api/speedtest", { method: "POST", headers: { "X-Down-Again": "1" } })).json();
    if (r.ok) {
      if (S.st && S.st.speed) S.st.speed.running = true;
      renderSpeedNow();
    } else {
      res.className = "res bad";
      res.textContent = { cooldown: t("speed.cooldown", { n: r.wait }), offline: t("speed.offline"), running: t("speed.busy") }[r.code] || r.code || "?";
    }
  } catch (e) { res.className = "res bad"; res.textContent = t("noContact"); }
};

$("#act-speed").onclick = () => { $("#speed-run").click(); $(".speed-now").scrollIntoView({ behavior: "smooth", block: "center" }); };

/* ---------- histórico ---------- */
function currentRange() {
  if (S.period === "custom" && S.custom) return S.custom;
  return NM.rangeFor(S.period === "custom" ? "7d" : S.period);
}

function pickPeriod(v) {
  S.period = v; NM.store.set("period", v);
  $("#period-seg").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.v === v));
  $("#custom").classList.toggle("on", v === "custom");
  if (v === "custom") {
    const r = S.custom || NM.rangeFor("7d");
    $("#d-from").value = r.from; $("#d-to").value = r.to;
  }
  S.limit = 40;
  if (S.tab === "history" || S.tab === "report") loadSummary();
}

async function loadSummary() {
  const r = currentRange();
  const qs = `from=${r.from}&to=${r.to}`;
  $("#lnk-report").href = "/relatorio?" + qs;
  $("#lnk-csv").href = `/api/outages.csv?${qs}&lang=${NM.lang}`;
  try {
    const [sum, speed] = await Promise.all([NM.get("/api/summary?" + qs), NM.get(`/api/speedtests?${qs}`)]);
    S.sum = sum; S.speed = speed;
    renderSummary(); renderSpeedChart();
  } catch (e) { /* mantém o último */ }
}
const loadSpeed = loadSummary;

function kpi(color, title, value, sub, tip) {
  return `<div class="card kpi" style="--c:${color}" ${tip ? `data-tip="${esc(tip)}"` : ""}><h3><i></i>${title}</h3><b>${value}</b><small>${sub}</small></div>`;
}

function renderSummary() {
  const s = S.sum;
  if (!s) return;
  const desc = s.days.length === 1 ? t("sum.oneDay", { day: NM.dayLabel(s.from), mon: dur(s.mon_s) }) :
    t("sum.range", { from: NM.date(s.from), to: NM.date(s.to - 1), mon: dur(s.mon_s) }) + (s.unmon_s > 60 ? t("sum.unmon", { d: dur(s.unmon_s) }) : "");
  setText($("#period-desc"), desc);
  renderReport();
  if (S.tab !== "history") return;

  const isp = s.causes.isp || { count: 0, down_s: 0 }, av = s.avail, sp = S.speed, plan = planNow();
  const avColor = av == null ? "var(--unknown)" : av >= 0.995 ? "var(--ok)" : av >= 0.98 ? "var(--warn)" : "var(--down)";
  const spAvg = sp && sp.down ? sp.down.avg : null;
  setHTML($("#kpis"), [
    kpi(avColor, t("gauge.label"), NM.pct(av, av != null && av < 0.9995 ? 2 : 1), av == null ? t("gauge.noData") : t("gauge.sub", { down: dur(s.down_s), mon: dur(s.mon_s) })),
    kpi("var(--down)", t("kpi.outages"), String(s.count), s.count ? t("kpi.outagesSub", { isp: isp.count, n: s.short }) : t("kpi.none"), t("kpi.ispTip")),
    kpi("var(--accent-2)", t("kpi.longest"), s.longest ? dur(s.longest.dur) : "—", s.longest ? esc(NM.dt(s.longest.start)) : "&nbsp;"),
    kpi("var(--unst)", t("kpi.unstable"), String(s.unstable.count), s.unstable.count ? t("kpi.unstableSub", { d: dur(s.unstable.dur_s) }) : t("kpi.none"), t("kpi.unstableTip")),
    kpi("var(--accent)", t("kpi.speed"), spAvg != null ? mbps(spAvg) : "—", spAvg != null && plan.down ? t("speed.ofPlan", { p: NM.pct(spAvg / plan.down, 0) }) : sp && sp.count ? t("kpi.speedTests", { n: sp.count }) : t("speed.empty")),
  ].join(""));

  setHTML($("#timeline"), NM.timelineHTML(s));
  renderHours();
  renderCauses();
  renderList();
  renderSpeedDesc();
}

function renderHours() {
  const s = S.sum;
  setHTML($("#hours"), s.count ? NM.hoursHTML(s.hours, S.hourMetric) : `<div class="empty">${t("hours.none")}</div>`);
}

function renderCauses() {
  const s = S.sum, total = s.down_s || 1;
  const keys = Object.keys(CAUSES).filter((k) => s.causes[k]);
  if (!keys.length) { setHTML($("#causes"), `<div class="empty">${t("causes.none")}</div>`); return; }
  setHTML($("#causes"), `<div class="stack">${keys.map((k) => `<i style="width:${(s.causes[k].down_s / total) * 100}%;background:${CAUSES[k].color}" data-tip="${esc(`<b>${CAUSES[k].label}</b><br>${t("causes.share", { p: NM.pct(s.causes[k].down_s / total, 0) })}`)}"></i>`).join("")}</div>
    <div class="clist">${keys.map((k) => `<div class="crow"><i style="background:${CAUSES[k].color}"></i>
      <div><b>${CAUSES[k].label}</b><small>${CAUSES[k].desc}</small></div>
      <div class="num"><b>${s.causes[k].count}×</b><small>${dur(s.causes[k].down_s)}</small></div></div>`).join("")}</div>`);
}

function allEvents() {
  const s = S.sum;
  return s.outages.map((o) => Object.assign({ kind: "outage" }, o))
    .concat(s.events.filter((x) => !(x.kind === "ip_change" && x.data && x.data.outage)));
}

function renderList() {
  const items = allEvents();
  const counts = { all: items.length, outage: 0, unstable: 0, ip_change: 0 };
  items.forEach((x) => { counts[x.kind]++; });
  const kinds = [["all", t("list.all"), "var(--text)"], ["outage", t("list.outages"), "var(--down)"],
    ["unstable", t("list.unstable"), "var(--unst)"], ["ip_change", t("list.ip"), "var(--accent)"]];
  setHTML($("#chips"), kinds.filter(([k]) => k === "all" || counts[k])
    .map(([k, l, c]) => `<button data-v="${k}" class="${S.filter === k ? "on" : ""}" style="--c:${c}"><i></i>${l} ${counts[k]}</button>`).join(""));
  let list = items.filter((x) => S.filter === "all" || x.kind === S.filter);
  const key = (x) => (x.kind === "ip_change" ? x.end : x.start);
  list = list.slice().sort(S.sort === "long" ? (a, b) => (b.dur || 0) - (a.dur || 0) : (a, b) => key(b) - key(a));
  const maxDur = Math.max(1, ...list.map((x) => (x.kind === "ip_change" ? 0 : x.dur)));
  setText($("#list-desc"), items.length ? t("list.desc", { n: S.sum.outages.length, u: counts.unstable }) : t("list.descNone"));
  if (!list.length) { setHTML($("#olist"), `<div class="empty">${t("list.empty")}</div>`); return; }
  setHTML($("#olist"), list.slice(0, S.limit).map((x) => eventRow(x, maxDur)).join("") +
    (list.length > S.limit ? `<button class="btn more" id="more">${t("list.more", { n: Math.min(40, list.length - S.limit), r: list.length - S.limit })}</button>` : ""));
  const more = $("#more");
  if (more) more.onclick = () => { S.limit += 40; renderList(); };
}

$("#chips").onclick = (e) => { const b = e.target.closest("button"); if (!b) return; S.filter = b.dataset.v; S.limit = 40; renderList(); };
$("#sort").onchange = (e) => { S.sort = e.target.value; renderList(); };
$("#timeline").onclick = (e) => {
  const el = e.target.closest(".s-out,.s-uns");
  if (!el) return;
  S.filter = "all"; S.sort = "recent"; $("#sort").value = "recent";
  const idx = allEvents().sort((a, b) => b.start - a.start).findIndex((x) => String(x.start) === el.dataset.start);
  if (idx >= S.limit) S.limit = idx + 10;
  renderList();
  const r = document.querySelector(`#olist .ev[data-start="${el.dataset.start}"]`);
  if (r) { r.scrollIntoView({ behavior: "smooth", block: "center" }); r.classList.add("flash"); setTimeout(() => r.classList.remove("flash"), 1800); }
};

/* ---------- velocidade no período ---------- */
function renderSpeedDesc() {
  const d = S.speed, plan = planNow();
  if (!d || !d.count) { setText($("#speed-desc"), t("speed.empty")); return; }
  setText($("#speed-desc"), t("speed.avg", { down: mbps(d.down && d.down.avg), up: mbps(d.up && d.up.avg) }) +
    (plan.down && d.below40 ? " · " + t("speed.below", { n: d.below40 }) : ""));
}

function renderSpeedChart() {
  if (S.tab === "history") drawSpeed($("#speed-chart"), S.speed, false, renderSpeedChart);
}

// Velocidade dos últimos 7 dias, no cartão da aba Agora.
async function loadSpeedRecent() {
  const r = NM.rangeFor("7d");
  try { S.speedRecent = await NM.get(`/api/speedtests?from=${r.from}&to=${r.to}`); renderSpeedMini(); } catch (e) { /* tenta depois */ }
}
function renderSpeedMini() {
  if (S.tab === "now") drawSpeed($("#speed-mini"), S.speedRecent, true, renderSpeedMini);
}

function drawSpeed(box, d, compact, retry) {
  if (!d) return;
  const tests = d.tests.filter((x) => !x.error && x.down);
  if (!tests.length) { setHTML(box, `<div class="empty chart-empty">${t("speed.empty")}</div>`); return; }
  const W = box.clientWidth, H = box.clientHeight, L = compact ? 34 : 46, R = compact ? 4 : 8, T = compact ? 6 : 10, B = compact ? 18 : 22;
  if (W < 120) return void setTimeout(retry, 300);
  const plan = planNow(), t0 = tests[0].ts, t1 = tests[tests.length - 1].ts, span = Math.max(1, t1 - t0);
  const X = (x) => (tests.length === 1 ? (L + W - R) / 2 : L + ((x - t0) / span) * (W - L - R));
  const yMax = niceMax(Math.max(10, plan.down, ...tests.map((x) => Math.max(x.down || 0, x.up || 0))) * 1.08);
  const Y = (v) => T + (1 - Math.min(v, yMax) / yMax) * (H - T - B);
  let g = axes(W, H, L, R, T, B, yMax, Y, compact ? 2 : 4);
  const nT = Math.min(W < 420 ? 2 : compact || W < 500 ? 3 : 5, tests.length - 1);
  for (let i = 0; i <= nT && tests.length > 1; i++) {
    const x = t0 + (span / nT) * i;
    g += `<text class="ax" x="${X(x)}" y="${H - 4}" text-anchor="${i === 0 ? "start" : i === nT ? "end" : "middle"}">${esc(span > 86400 ? NM.dayLabel(x) : NM.time(x, false))}</text>`;
  }
  if (plan.down) {
    g += `<line class="sp-plan-line" x1="${L}" x2="${W - R}" y1="${Y(plan.down)}" y2="${Y(plan.down)}"/>`;
    if (!compact) g += `<line class="sp-40-line" x1="${L}" x2="${W - R}" y1="${Y(plan.down * 0.4)}" y2="${Y(plan.down * 0.4)}"/>`;
  }
  const line = (key) => tests.filter((x) => x[key] != null).map((x, i) => `${i ? "L" : "M"}${X(x.ts).toFixed(1)} ${Y(x[key]).toFixed(1)}`).join("");
  const dots = (key, cls) => compact ? "" : tests.filter((x) => x[key] != null).map((x) => `<circle class="${cls}" cx="${X(x.ts).toFixed(1)}" cy="${Y(x[key]).toFixed(1)}" r="2.6"/>`).join("");
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}">${g}<path class="l-up" d="${line("up")}"/><path class="l-avg" d="${line("down")}"/>${dots("up", "d-up")}${dots("down", "d-down")}
    <line class="xh" y1="${T}" y2="${H - B}"/><rect class="ov" x="${L}" y="0" width="${W - L - R}" height="${H}" fill="transparent"/></svg>`;
  box._html = null;
  const ov = box.querySelector(".ov"), xh = box.querySelector(".xh");
  const move = (cx, cy) => {
    const at = t0 + ((cx - box.getBoundingClientRect().left - L) / (W - L - R)) * span;
    let best = tests[0];
    for (const x of tests) if (Math.abs(x.ts - at) < Math.abs(best.ts - at)) best = x;
    xh.setAttribute("x1", X(best.ts)); xh.setAttribute("x2", X(best.ts));
    box.classList.add("hover");
    tips.show(cx, cy, t("speed.tip", { dt: esc(NM.dt(best.ts)), down: mbps(best.down), up: mbps(best.up), ping: NM.ms(best.ping) }));
  };
  ov.addEventListener("mousemove", (e) => move(e.clientX, e.clientY));
  ov.addEventListener("touchstart", (e) => move(e.touches[0].clientX, e.touches[0].clientY), { passive: true });
  ov.addEventListener("touchmove", (e) => move(e.touches[0].clientX, e.touches[0].clientY), { passive: true });
  ov.addEventListener("mouseleave", () => { box.classList.remove("hover"); tips.hide(); });
}

/* ---------- relatório ---------- */
function renderReport() {
  const s = S.sum, sp = S.speed, plan = planNow();
  if (!s) return;
  setText($("#rep-period"), t("r.periodRange", { a: NM.date(s.from), b: NM.date(s.to - 1) }));
  const isp = s.causes.isp || { count: 0, down_s: 0 };
  const spAvg = sp && sp.down ? sp.down.avg : null;
  const facts = [
    [t("r.avail"), NM.pct(s.avail, 3)],
    [t("r.count"), s.count ? t("rep.outages", { n: s.count, isp: isp.count }) : "0"],
    [t("r.offline"), dur(s.down_s)],
    [t("r.longest"), s.longest ? t("r.longestVal", { d: dur(s.longest.dur), dt: NM.dtFull(s.longest.start) }) : "—"],
    [t("r.unstable"), s.unstable.count ? `${s.unstable.count} (${dur(s.unstable.dur_s)})` : "0"],
    [t("r.speedDown"), spAvg == null ? "—" : plan.down ? t("r.speedPct", { v: mbps(spAvg), p: NM.pct(spAvg / plan.down, 0) }) : mbps(spAvg)],
    [t("r.ipChanges"), String(s.ip_changes)],
    [t("r.monitored"), dur(s.mon_s) + (s.unmon_s > 60 ? " · " + t("rep.unmon", { d: dur(s.unmon_s) }) : "")],
  ];
  setHTML($("#rep-facts"), facts.map(([a, b]) => `<dt>${esc(a)}</dt><dd>${esc(b)}</dd>`).join(""));
}

/* ---------- ajustes ---------- */
async function saveSetting(changes) {
  try {
    const r = await (await fetch("/api/settings", { method: "POST", headers: { "X-Down-Again": "1", "Content-Type": "application/json" }, body: JSON.stringify(changes) })).json();
    if (!r.ok) throw new Error(r.code);
    Object.assign(S.cfg, r.settings);
    toast(t("speed.saved"));
    renderSettings(); renderSpeedNow(); renderSpeedMini();
    return true;
  } catch (err) { toast(t("ntfy.failed", { e: err.message }), false); return false; }
}

const opt = (v, label, cur) => `<option value="${v}"${String(v) === String(cur) ? " selected" : ""}>${esc(label)}</option>`;

function renderSettings() {
  const c = S.cfg;
  if (!c) return;
  if (document.activeElement && document.activeElement.matches("#v-settings select")) return;   // não fecha a lista aberta
  const hours = [-1, 6, 7, 8, 9, 10, 12, 18, 20, 22];
  if (!hours.includes(c.daily_summary_hour)) hours.push(c.daily_summary_hour);
  $("#set-daily").innerHTML = hours.sort((a, b) => a - b).map((h) => opt(h, h < 0 ? t("set.off") : t("set.at", { h: NM.pad(h) + ":00" }), c.daily_summary_hour)).join("");
  const mins = [0, 30, 60, 300, 900];
  if (!mins.includes(c.notify_min_seconds)) mins.push(c.notify_min_seconds);
  $("#set-min").innerHTML = mins.sort((a, b) => a - b).map((s) => opt(s, s ? t("set.longer", { d: dur(s) }) : t("set.all"), c.notify_min_seconds)).join("");
  $("#set-lang").innerHTML = opt("auto", t("set.auto"), c.language_setting) + NM.LANGS.map((l) => opt(l.code, l.name, c.language_setting)).join("");
  $("#set-speed").innerHTML = c.speed_choices.map((m) => opt(m, !m ? t("set.off") : m === 1440 ? t("set.daily1") :
    t("set.every", { d: m % 60 ? `${m} ${t("unit.min")}` : `${m / 60} ${t("unit.h")}`, n: Math.round(1440 / m) }), c.speedtest_minutes)).join("");
  // franquia: cada teste baixa e envia durante speedtest_seconds na velocidade do plano (ou do último teste)
  const last = S.st && S.st.speed && S.st.speed.last, plan = planNow();
  const down = plan.down || (last && last.down) || 0, up = plan.up || (last && last.up) || 0;
  const gb = c.speedtest_minutes && down ? ((down + up) * c.speedtest_seconds / 8) * (1440 / c.speedtest_minutes) * 30 / 1000 : null;
  $("#speed-usage").textContent = !c.speedtest_minutes ? t("set.usageOff") : gb != null ? t("set.usage", { gb: NM.num(gb, gb < 10 ? 1 : 0), s: c.speedtest_seconds }) : "";
  if (document.activeElement !== $("#plan-down")) $("#plan-down").value = plan.down || "";
  if (document.activeElement !== $("#plan-up")) $("#plan-up").value = plan.up || "";

  $("#topic").textContent = c.ntfy_topic || t("ntfy.disabled");
  $("#ntfy-step2").innerHTML = t("ntfy.step2", { server: esc(c.ntfy_server.replace(/^https?:\/\//, "")) });
  const n = c.notify, now = nowS();
  $("#ntfy-state").innerHTML = !n ? "" : [n.last_sent ? t("ntfy.lastSent", { d: ago(now - n.last_sent) }) : t("ntfy.never"),
    n.pending ? t("ntfy.pending", { n: n.pending }) : "", n.error ? `<span class="bad">${esc(t("ntfy.lastError", { e: n.error }))}</span>` : ""].filter(Boolean).join(" · ");

  const addr = c.host ? `${c.host}:${c.port}` : "", ip = S.st && S.st.public_ip;
  $("#about").innerHTML = [[t("about.address"), addr ? `http://${addr}` : location.origin], [t("about.localIp"), c.ip || "—"],
    [t("about.publicIp"), ip ? ip.ip : "—"], [t("about.system"), c.platform], [t("about.checks"), t("about.every", { n: c.interval })]]
    .map(([a, b]) => `<dt>${esc(a)}</dt><dd>${esc(b)}</dd>`).join("");
}

document.querySelectorAll("#v-settings select[data-k]").forEach((sel) => {
  sel.onchange = () => saveSetting({ [sel.dataset.k]: sel.dataset.k === "language" ? sel.value : Number(sel.value) });
});

$("#sp-form").onsubmit = async (e) => {
  e.preventDefault();
  const ok = await saveSetting({ plan_down_mbps: Number($("#plan-down").value || 0), plan_up_mbps: Number($("#plan-up").value || 0) });
  $("#plan-res").className = "res " + (ok ? "ok" : "bad");
  $("#plan-res").textContent = ok ? t("speed.saved") : "";
};

$("#copy").onclick = async () => {
  const topic = $("#topic").textContent;
  try { await navigator.clipboard.writeText(topic); $("#copy").textContent = t("ntfy.copied"); }
  catch (e) { const r = document.createRange(); r.selectNodeContents($("#topic")); const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r); $("#copy").textContent = t("ntfy.selected"); }
  setTimeout(() => { $("#copy").textContent = t("ntfy.copy"); }, 1600);
};
$("#test").onclick = async () => {
  const res = $("#test-res");
  res.className = "res"; res.textContent = t("ntfy.sending");
  try {
    // fetch direto: respostas 403/429 também trazem o motivo em JSON
    const r = await (await fetch("/api/test-notify?lang=" + NM.lang, { method: "POST", headers: { "X-Down-Again": "1" } })).json();
    res.className = "res " + (r.ok ? "ok" : "bad");
    const why = { cooldown: t("ntfy.cooldown", { n: r.wait }), disabled: t("ntfy.disabled"), refused: t("ntfy.refused") }[r.code] || r.error || "?";
    res.textContent = r.ok ? t("ntfy.sent") : t("ntfy.failed", { e: why });
  } catch (e) { res.className = "res bad"; res.textContent = t("noContact"); }
};

async function loadConfig() {
  try {
    S.cfg = await NM.get("/api/config");
    renderSettings();
    renderPhone();
    renderSpeedNow();
    if (S.tab === "history") { renderSpeedChart(); renderSummary(); }
    renderSpeedMini();
    const addr = S.cfg.host ? `http://${S.cfg.host}:${S.cfg.port}` : "";
    $("#foot").innerHTML = esc(t("foot", { n: S.cfg.interval })) + (addr ? ` · <a href="${esc(addr)}">${esc(addr)}</a>` : "");
  } catch (e) { setTimeout(loadConfig, 5000); }
}

/* ---------- celular: aviso de instalar e QR code ---------- */
const UA = navigator.userAgent;
const IS_IOS = /iPhone|iPad|iPod/.test(UA) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
const IS_PHONE = IS_IOS || /Android|Mobi/i.test(UA);
const STANDALONE = matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
const SHARE_ICON = `<svg class="share" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12M8 7l4-4 4 4"/><path d="M6 11v9h12v-9"/></svg>`;
let installPrompt = null;   // só existe no Android/Chrome em HTTPS ou localhost

// iPhone não deixa site se adicionar sozinho: mostramos o caminho pelo botão Compartilhar.
const installHow = () => (IS_IOS ? t("install.ios", { share: SHARE_ICON }) : t("install.android"));

function renderInstall() {
  $("#install").hidden = !(IS_PHONE && !STANDALONE && !NM.store.get("installHidden", false));
  $("#install-how").innerHTML = installHow();
  $("#install-btn").hidden = !installPrompt;
}

async function promptInstall() {
  if (!installPrompt) return;
  installPrompt.prompt();
  await installPrompt.userChoice;
  installPrompt = null;
  renderInstall();
  renderPhone();
}

function renderPhone() {
  const box = $("#phone-body");
  if (STANDALONE) { box.innerHTML = `<p>${t("phone.installed")}</p>`; return; }
  if (IS_PHONE) {
    box.innerHTML = `<p>${installHow()}</p>` +
      (installPrompt ? `<div class="btns" style="margin-top:12px"><button class="btn primary" id="phone-install">${t("install.button")}</button></div>` : "");
    if (installPrompt) $("#phone-install").onclick = promptInstall;
    return;
  }
  // No computador: QR com o nome .local (endereço que não muda); o IP fica como alternativa.
  const cfg = S.cfg || {}, port = cfg.port || location.port;
  const url = cfg.host ? `http://${cfg.host}:${port}` : cfg.ip ? `http://${cfg.ip}:${port}` : location.origin;
  const alt = cfg.host && cfg.ip ? `${cfg.ip}:${port}` : url.replace(/^https?:\/\//, "");
  const code = QR.svg(url);
  setHTML(box, (code ? `<div class="qr">${code}</div>` : "") + `<p>${t("phone.desc")}</p>` +
    `<p class="muted">${t("phone.or", { url: `<code>${esc(alt)}</code>` })}</p>`);
}

$("#install-x").onclick = () => { NM.store.set("installHidden", true); renderInstall(); };
$("#install-btn").onclick = promptInstall;
window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); installPrompt = e; renderInstall(); renderPhone(); });
window.addEventListener("appinstalled", () => { NM.store.set("installHidden", true); renderInstall(); });

/* ---------- controles ---------- */
seg($("#series-seg"), S.seriesH, (v) => { S.seriesH = v; NM.store.set("series", v); loadSeries(); });
seg($("#hour-seg"), S.hourMetric, (v) => { S.hourMetric = v; renderHours(); });
seg($("#period-seg"), S.period, pickPeriod);
$("#custom").classList.toggle("on", S.period === "custom");
if (S.period === "custom" && S.custom) { $("#d-from").value = S.custom.from; $("#d-to").value = S.custom.to; }
$("#d-apply").onclick = () => {
  if (!$("#d-from").value || !$("#d-to").value) return;
  S.custom = { from: $("#d-from").value, to: $("#d-to").value }; NM.store.set("custom", S.custom); loadSummary();
};

$("#refresh").onclick = async () => {
  const b = $("#refresh");
  if (b.classList.contains("spin")) return;
  b.classList.add("spin");
  const work = [pollStatus(), loadGlance(), new Promise((r) => setTimeout(r, 600))];
  if (S.tab === "now") work.push(loadSeries());
  if (S.tab === "history" || S.tab === "report") work.push(loadSummary());
  if (S.tab === "settings") work.push(loadConfig());
  await Promise.all(work);
  b.classList.remove("spin");
};

let rT;
window.addEventListener("resize", () => { clearTimeout(rT); rT = setTimeout(() => { renderSeries(); renderSpeedChart(); renderSpeedMini(); }, 120); });

/* ---------- início e atualizações ---------- */
// Aba escondida (outra aba do navegador, tela apagada): não busca nem redesenha nada.
const live = (fn) => () => { if (!document.hidden) fn(); };
document.addEventListener("visibilitychange", () => { if (!document.hidden) { pollStatus(); loadGlance(); } });

renderInstall();
renderPhone();
showTab(location.hash.slice(1));
loadConfig();
pollStatus();
loadGlance();
setInterval(live(pollStatus), 3000);
setInterval(live(loadGlance), 30000);
setInterval(live(renderHero), 1000);
setInterval(live(() => { if (S.tab === "history" || S.tab === "report") loadSummary(); }), 60000);
setInterval(live(() => { if (S.tab === "now") loadSeries(); }), 30000);
setInterval(live(() => { if (S.tab === "settings") loadConfig(); }), 30000);
