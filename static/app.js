"use strict";
const $ = (s) => document.querySelector(s);
const { esc, dur, cause, CAUSES, t } = NM;
const tips = NM.initTips();
NM.applyStatic();
NM.mountLangMenu($("#lang"), $("#lang-menu"));

const S = {
  cfg: null, st: null, offset: 0, sum: null, series: null, failCount: 0,
  period: NM.store.get("period", "today"), custom: NM.store.get("custom", null),
  seriesH: NM.store.get("series", "6"), hourMetric: "count", filter: "all", sort: "recent", limit: 40,
};
const nowS = () => Date.now() / 1000 + S.offset;

/* ---------- tema ---------- */
const DARK_FROM = 18, DARK_TO = 6;   // "pelo horário": escuro das 18h às 6h
const ICONS = {
  hour: `<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>`,
  system: `<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>`,
  light: `<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>`,
  dark: `<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>`,
};
const THEMES = [
  ["hour", t("theme.hour"), t("theme.hourHint", { a: DARK_FROM, b: DARK_TO })],
  ["system", t("theme.system"), t("theme.systemHint")],
  ["light", t("theme.light"), ""],
  ["dark", t("theme.dark"), ""],
];
const svg = (k) => `<svg viewBox="0 0 24 24">${ICONS[k]}</svg>`;
let theme = NM.store.get("tema", "hour");

function applyTheme() {
  let th = theme;
  if (th === "hour") { const h = new Date().getHours(); th = h >= DARK_FROM || h < DARK_TO ? "dark" : "light"; }
  if (th === "system") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = th;
  const shown = th === "system" ? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light") : th;
  // ícone do botão = o que está na tela agora (sol/lua), ou relógio/tela quando é automático
  $("#theme").innerHTML = svg(theme === "hour" || theme === "system" ? theme : shown);
  $("#theme").title = t("theme.title", { t: THEMES.find((x) => x[0] === theme)[1].toLowerCase() });
  $("#theme").setAttribute("aria-label", t("theme"));
  document.querySelector('meta[name="theme-color"]').content = shown === "dark" ? "#080c15" : "#f2f4f9";
  $("#theme-menu").innerHTML = THEMES.map(([k, l, h]) =>
    `<button role="menuitemradio" aria-checked="${k === theme}" data-v="${k}" class="${k === theme ? "on" : ""}">${svg(k)}<span>${l}${h ? `<small>${h}</small>` : ""}</span><span>${k === theme ? "✓" : ""}</span></button>`).join("");
}
const toggleMenu = (open) => { $("#theme-menu").classList.toggle("on", open); $("#theme").setAttribute("aria-expanded", open); };
$("#theme").onclick = (e) => { e.stopPropagation(); $("#lang-menu").classList.remove("on"); toggleMenu(!$("#theme-menu").classList.contains("on")); };
$("#theme-menu").onclick = (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  theme = b.dataset.v; NM.store.set("tema", theme); applyTheme(); toggleMenu(false);
};
document.addEventListener("click", () => toggleMenu(false));
document.addEventListener("keydown", (e) => { if (e.key === "Escape") toggleMenu(false); });
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyTheme);
applyTheme();
setInterval(applyTheme, 60000);

/* ---------- segmentados ---------- */
function seg(el, value, onPick) {
  const set = (v) => el.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.v === v));
  set(value);
  el.onclick = (e) => { const b = e.target.closest("button"); if (!b) return; set(b.dataset.v); onPick(b.dataset.v); };
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
  if (st.pending) return { cls: "warn", title: t("hero.unstable"), lbl: t("hero.onlineFor"), big: NM.clock(now - st.since),
    sub: t("hero.unstable.sub", { n: st.pending }) };
  return { cls: "up", title: t("hero.online"), lbl: st.since_start ? t("hero.monitoringFor") : t("hero.noOutagesFor"), big: NM.clock(now - st.since),
    sub: esc(st.since_start ? t("hero.sinceStart", { dt: NM.dt(st.since) }) : t("hero.lastEnded", { dt: NM.dt(st.since) })) };
}

function renderHero() {
  const h = heroState();
  $("#status").className = "card status is-" + h.cls;
  document.body.dataset.state = h.cls;
  $("#st-title").textContent = h.title;
  $("#st-lbl").textContent = h.lbl;
  $("#st-big").textContent = h.big;
  $("#st-sub").innerHTML = h.sub;
  const color = { up: "#12b76a", down: "#f04438", warn: "#f79009", idle: "#98a2b3" }[h.cls];
  document.title = (h.cls === "down" ? t("title.down", { t: h.big }) : h.title) + " · down-again";
  if (renderHero.last !== h.cls) { favicon(color); renderHero.last = h.cls; }
}

function setNode(id, cls, text) { const n = $(id); n.className = "node " + cls; n.querySelector("small").textContent = text; }
function setLink(id, cls) { $(id).className = "link " + cls; }

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
  $("#path-note").textContent = p.state === "ok" ? t("note.ok", { n: st.interval }) : t("note." + p.state);
}

function renderNet() {
  const net = S.st && S.st.net;
  $("#netchip").dataset.tip = t("net.tip");
  if (!net || !net.kind) {
    $("#neticon").innerHTML = NM.wifiIcon(4, "off"); $("#netname").textContent = t("net.none"); $("#netsub").textContent = ""; return;
  }
  if (net.kind === "cabo") {
    $("#neticon").innerHTML = `<svg class="wifi" viewBox="0 0 24 24"><path class="on" d="M9 3v4M15 3v4M7 7h10v5a5 5 0 0 1-10 0zM12 17v4"/></svg>`;
    $("#netname").textContent = t("net.cable");
    $("#netsub").textContent = net.port || net.iface || "";
    // dataset recebe HTML pronto (não passa pelo parser): escapa só os valores vindos do sistema
    $("#netchip").dataset.tip = `<b>${t("net.cableTip")}</b><br>${esc(net.port || "")} (${esc(net.iface || "")})`;
    return;
  }
  const sig = NM.signal(net.rssi);
  $("#neticon").innerHTML = NM.wifiIcon(net.rssi == null ? 4 : sig.bars);   // sem leitura de sinal: ícone cheio
  $("#netname").textContent = net.ssid || "Wi-Fi";
  $("#netsub").textContent = net.rssi != null ? `${Math.round(net.rssi)} dBm · ${sig.label}` : "";
  $("#netchip").dataset.tip = `<b>${esc(net.ssid || "Wi-Fi")}</b><br>` +
    [net.rssi != null && t("net.signal", { v: `${Math.round(net.rssi)} dBm (${sig.label})` }),
     net.noise != null && t("net.noise", { v: `${Math.round(net.noise)} dBm` }),
     net.channel && t("net.channel", { v: esc(net.channel) }),
     net.tx_rate && t("net.link", { v: Math.round(net.tx_rate) })].filter(Boolean).join("<br>");
}

async function pollStatus() {
  try {
    const st = await NM.get("/api/status");
    S.offset = st.now - Date.now() / 1000;
    const changed = !S.st || S.st.state !== st.state || (S.st.outage && S.st.outage.start) !== (st.outage && st.outage.start);
    const lastSpeed = (x) => (x && x.speed && x.speed.last ? x.speed.last.ts : null);
    const newSpeed = S.st && lastSpeed(st) !== lastSpeed(S.st);
    S.st = st; S.failCount = 0;
    renderPath(); renderNet(); renderSpeedVals();
    if (newSpeed) loadSpeed();
    if (changed) { loadSummary(); loadSeries(); loadGlance(); }
  } catch (e) {
    if (++S.failCount >= 2) { S.st = null; renderPath(); }
  }
  renderHero();
}

/* ---------- resposta rápida: últimas 24h ---------- */
const GL_ICONS = {
  ok: `<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.7 2.7L16 9.5"/></svg>`,
  bad: `<svg viewBox="0 0 24 24"><path d="M12 3.5l9 16H3z"/><path d="M12 10v4M12 17h.01"/></svg>`,
};

async function loadGlance() {
  try { S.gl = await NM.get("/api/glance"); renderGlance(); } catch (e) { /* tenta no próximo ciclo */ }
}

function renderGlance() {
  const g = S.gl, now = nowS(), h = g.h24, last = g.last;   // relógio do servidor, atualizado a cada segundo
  const young = g.since && now - g.since < 86400;            // monitor rodando há menos de 24h
  $("#gl-title").textContent = !h.count ? t("gl.none") : h.count === 1 ? t("gl.one") : t("gl.many", { n: h.count });
  $("#gl-sub").textContent = last && last.ongoing ? t("gl.downNow") :
    last ? t("gl.last", { d: dur(now - last.end) }) : young ? t("gl.monitoring", { d: dur(now - g.since) }) : t("gl.never");
  $("#glance").className = "card glance " + (h.count ? (last && last.ongoing ? "bad" : "warn") : "ok");
  $("#gl-ic").innerHTML = GL_ICONS[h.count ? "bad" : "ok"];
  const tile = (label, w, period) => `<${period ? `button data-p="${period}"` : "div"} class="gl-tile">
      <span>${label}</span><b class="${w.count ? "" : "z"}">${w.count}</b></${period ? "button" : "div"}>`;
  $("#gl-tiles").innerHTML = tile("24h", h) + tile(t("p.7d"), g.d7, "7d") + tile(t("p.30d"), g.d30, "30d");
}

$("#gl-tiles").onclick = (e) => {
  const b = e.target.closest("[data-p]");
  if (!b) return;
  document.querySelector(`#period-seg [data-v="${b.dataset.p}"]`).click();
  $("#period-seg").closest("section").scrollIntoView({ behavior: "smooth", block: "start" });
};

/* ---------- gráfico de latência ---------- */
async function loadSeries() {
  try { S.series = await NM.get("/api/timeseries?hours=" + S.seriesH); renderSeries(); } catch (e) { /* tenta no próximo ciclo */ }
}

function niceMax(v) {
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

function renderSeries() {
  const box = $("#chart"), d = S.series;
  if (!d) return;
  const W = box.clientWidth, H = box.clientHeight, L = 38, R = 6, T = 8, B = 22;
  if (W < 120) return void setTimeout(renderSeries, 300);   // ainda sem layout: tenta de novo
  const pts = d.points, span = d.now - d.from;
  const X = (x) => L + ((x - d.from) / span) * (W - L - R);
  const vals = pts.map((p) => p.max).filter((v) => v != null).sort((a, b) => a - b);
  const cap = vals.length ? vals[Math.floor(vals.length * 0.98)] : 50;
  const yMax = niceMax(Math.max(20, cap * 1.1));
  const Y = (v) => T + (1 - Math.min(v, yMax) / yMax) * (H - T - B);
  const bw = Math.max(1.5, (d.step / span) * (W - L - R));
  let g = "";
  for (let i = 0; i <= 4; i++) {
    const v = (yMax / 4) * i, y = Y(v);
    g += `<line class="gl" x1="${L}" x2="${W - R}" y1="${y}" y2="${y}"/><text class="ax" x="${L - 6}" y="${y + 3.5}" text-anchor="end">${Math.round(v)}</text>`;
  }
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
  const area = (() => {
    // área sob a média, quebrando nos buracos
    let out = "", run = [];
    const flush = () => {
      if (run.length > 1) out += `M${X(run[0].t + d.step / 2)} ${Y(0)}` + run.map((p) => `L${X(p.t + d.step / 2)} ${Y(p.avg)}`).join("") + `L${X(run[run.length - 1].t + d.step / 2)} ${Y(0)}Z`;
      run = [];
    };
    pts.forEach((p) => {
      if (p.avg == null || (run.length && p.t - run[run.length - 1].t > d.step * 1.6)) flush();
      if (p.avg != null) run.push(p);
    });
    flush();
    return out;
  })();
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}">
    <defs><linearGradient id="ga" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="var(--accent)" stop-opacity=".32"/><stop offset="1" stop-color="var(--accent)" stop-opacity="0"/></linearGradient></defs>
    ${g}${fails}<path d="${area}" fill="url(#ga)"/><path class="l-gw" d="${line("gw")}"/><path class="l-avg" d="${line("avg")}"/>
    <line class="xh" id="xh" y1="${T}" y2="${H - B}"/><circle class="dot" id="xd" r="4.5"/>
    <rect id="ov" x="${L}" y="0" width="${W - L - R}" height="${H}" fill="transparent"/></svg>`;
  if (!pts.length) box.insertAdjacentHTML("beforeend", `<div class="empty" style="position:absolute;inset:0;display:grid;place-items:center"><span>${t("chart.empty")}</span></div>`);
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

/* ---------- velocidade ---------- */
const mbps = (v) => (v == null ? "—" : `${NM.num(v, v < 10 ? 1 : 0)} Mbps`);
// "há X" com resolução de minutos: o cartão só é refeito quando o texto muda (poupa CPU)
const mins = (sec) => (sec < 60 ? `< 1 ${t("unit.min")}` : sec < 3600 ? `${Math.round(sec / 60)} ${t("unit.min")}` : dur(Math.round(sec / 60) * 60));
const planNow = () => ({ down: Number((S.cfg && S.cfg.plan_down_mbps) || 0), up: Number((S.cfg && S.cfg.plan_up_mbps) || 0) });

async function loadSpeed() {
  const r = currentRange();
  try { S.speed = await NM.get(`/api/speedtests?from=${r.from}&to=${r.to}`); renderSpeedChart(); renderSpeedDesc(); } catch (e) { /* tenta no próximo ciclo */ }
}

function renderSpeedDesc() {
  const d = S.speed, plan = planNow();
  if (!d || !d.count) { $("#speed-desc").innerHTML = "&nbsp;"; return; }
  $("#speed-desc").textContent = t("speed.avg", { down: mbps(d.down && d.down.avg), up: mbps(d.up && d.up.avg) }) +
    (plan.down && d.below40 ? " · " + t("speed.below", { n: d.below40 }) : "");
}

function speedRow(label, value, plan, color) {
  const pct = plan && value != null ? value / plan : null;
  return `<div class="sp-row"><span class="sp-lbl">${label}</span><b>${value == null ? "—" : NM.num(value, value < 10 ? 1 : 0)}</b><small>Mbps</small>` +
    (pct != null ? `<span class="sp-pct${pct < 0.4 ? " low" : ""}">${t("speed.ofPlan", { p: NM.pct(pct, 0) })}</span>` : "") + `</div>` +
    `<div class="sp-bar"><i style="width:${pct != null ? Math.min(100, pct * 100) : value != null ? 100 : 0}%;--c:${color}"></i></div>`;
}

function renderSpeedVals() {
  const sp = S.st && S.st.speed, plan = planNow(), now = nowS();
  let html = "";
  if (sp) {
    const l = sp.last;
    if (!l) html = `<p class="sp-meta">${t(sp.enabled ? "speed.none" : "speed.off")}</p>`;
    else if (l.error) html = `<p class="sp-meta">${esc(t("speed.failedLast", { e: l.error }))}</p>`;
    else {
      html = speedRow("↓ " + t("speed.download"), l.down, plan.down, "var(--accent)") + speedRow("↑ " + t("speed.upload"), l.up, plan.up, "var(--ok)") +
        `<p class="sp-meta">${t("speed.ping", { p: NM.ms(l.ping), j: NM.ms(l.jitter) })}</p>`;
    }
    const when = sp.running ? t("speed.running") : [l && t("speed.last", { d: mins(now - l.ts) }),
      sp.enabled ? sp.next && t("speed.next", { d: mins(Math.max(0, sp.next - now)) }) : t("speed.off")].filter(Boolean).join(" · ");
    html += `<p class="sp-meta">${esc(when)}</p>`;
  }
  if (html !== renderSpeedVals.html) { $("#speed-vals").innerHTML = html; renderSpeedVals.html = html; }
  const busy = !!(sp && sp.running);
  $("#speed-run").classList.toggle("busy", busy);
  $("#speed-run").disabled = busy;
}

function renderSpeedChart() {
  const box = $("#speed-chart"), d = S.speed;
  if (!d) return;
  const tests = d.tests.filter((x) => !x.error && x.down);
  if (!tests.length) { box.innerHTML = `<div class="empty" style="height:100%;display:grid;place-items:center">${t("speed.empty")}</div>`; return; }
  const W = box.clientWidth, H = box.clientHeight, L = 46, R = 8, T = 10, B = 22;
  if (W < 120) return void setTimeout(renderSpeedChart, 300);
  const plan = planNow(), t0 = tests[0].ts, t1 = tests[tests.length - 1].ts, span = Math.max(1, t1 - t0);
  const X = (x) => (tests.length === 1 ? (L + W - R) / 2 : L + ((x - t0) / span) * (W - L - R));
  const yMax = niceMax(Math.max(10, plan.down, ...tests.map((x) => Math.max(x.down || 0, x.up || 0))) * 1.08);
  const Y = (v) => T + (1 - Math.min(v, yMax) / yMax) * (H - T - B);
  let g = "";
  for (let i = 0; i <= 4; i++) {
    const v = (yMax / 4) * i, y = Y(v);
    g += `<line class="gl" x1="${L}" x2="${W - R}" y1="${y}" y2="${y}"/><text class="ax" x="${L - 6}" y="${y + 3.5}" text-anchor="end">${Math.round(v)}</text>`;
  }
  const nT = Math.min(W < 500 ? 3 : 5, tests.length - 1);
  for (let i = 0; i <= nT && tests.length > 1; i++) {
    const x = t0 + (span / nT) * i;
    g += `<text class="ax" x="${X(x)}" y="${H - 5}" text-anchor="${i === 0 ? "start" : i === nT ? "end" : "middle"}">${esc(span > 86400 ? NM.dayLabel(x) : NM.time(x, false))}</text>`;
  }
  if (plan.down) {
    g += `<line class="sp-plan-line" x1="${L}" x2="${W - R}" y1="${Y(plan.down)}" y2="${Y(plan.down)}"/>`;
    g += `<line class="sp-40-line" x1="${L}" x2="${W - R}" y1="${Y(plan.down * 0.4)}" y2="${Y(plan.down * 0.4)}"/>`;
  }
  const line = (key) => tests.filter((x) => x[key] != null).map((x, i) => `${i ? "L" : "M"}${X(x.ts).toFixed(1)} ${Y(x[key]).toFixed(1)}`).join("");
  const dots = (key, cls) => tests.filter((x) => x[key] != null).map((x) => `<circle class="${cls}" cx="${X(x.ts).toFixed(1)}" cy="${Y(x[key]).toFixed(1)}" r="2.6"/>`).join("");
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}">${g}<path class="l-up" d="${line("up")}"/><path class="l-avg" d="${line("down")}"/>${dots("up", "d-up")}${dots("down", "d-down")}
    <line class="xh" id="sxh" y1="${T}" y2="${H - B}"/><rect id="sov" x="${L}" y="0" width="${W - L - R}" height="${H}" fill="transparent"/></svg>`;
  const ov = box.querySelector("#sov"), xh = box.querySelector("#sxh");
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

$("#speed-run").onclick = async () => {
  const res = $("#speed-res");
  res.className = "res"; res.textContent = "";
  try {
    const r = await (await fetch("/api/speedtest", { method: "POST", headers: { "X-Down-Again": "1" } })).json();
    if (r.ok) {
      if (S.st && S.st.speed) S.st.speed.running = true;
      renderSpeedVals();
    } else {
      res.className = "res bad";
      res.textContent = { cooldown: t("speed.cooldown", { n: r.wait }), offline: t("speed.offline"), running: t("speed.busy") }[r.code] || r.code || "?";
    }
  } catch (e) { res.className = "res bad"; res.textContent = t("noContact"); }
};

$("#sp-form").onsubmit = async (e) => {
  e.preventDefault();
  const res = $("#plan-res");
  try {
    const body = JSON.stringify({ down: Number($("#plan-down").value || 0), up: Number($("#plan-up").value || 0) });
    const r = await (await fetch("/api/plan", { method: "POST", headers: { "X-Down-Again": "1", "Content-Type": "application/json" }, body })).json();
    if (!r.ok) throw new Error(r.code);
    S.cfg.plan_down_mbps = r.plan.down; S.cfg.plan_up_mbps = r.plan.up;
    res.className = "res ok"; res.textContent = t("speed.saved");
    renderPlanForm(); renderSpeedVals.html = null; renderSpeedVals(); renderSpeedChart(); renderSpeedDesc();
  } catch (err) { res.className = "res bad"; res.textContent = t("ntfy.failed", { e: err.message }); }
};

function renderPlanForm() {
  const plan = planNow();
  if (document.activeElement !== $("#plan-down")) $("#plan-down").value = plan.down || "";
  if (document.activeElement !== $("#plan-up")) $("#plan-up").value = plan.up || "";
  $("#sp-plan-sum").textContent = t("speed.plan") + (plan.down ? `: ${NM.num(plan.down)} / ${NM.num(plan.up)} Mbps` : "");
  if (!plan.down) $("#sp-plan").open = true;      // sem plano: já mostra o formulário
}

/* ---------- resumo do período ---------- */
function currentRange() {
  if (S.period === "custom" && S.custom) return S.custom;
  return NM.rangeFor(S.period === "custom" ? "7d" : S.period);
}

async function loadSummary() {
  const r = currentRange();
  const qs = `from=${r.from}&to=${r.to}`;
  $("#lnk-report").href = "/relatorio?" + qs;
  $("#lnk-csv").href = `/api/outages.csv?${qs}&lang=${NM.lang}`;
  loadSpeed();
  try { S.sum = await NM.get("/api/summary?" + qs); renderSummary(); } catch (e) { /* mantém o último */ }
}

function kpi(color, title, value, sub, tip) {
  return `<div class="card kpi" style="--c:${color}" ${tip ? `data-tip="${esc(tip)}"` : ""}><h3><i></i>${title}</h3><b>${value}</b><small>${sub}</small></div>`;
}

function renderSummary() {
  const s = S.sum;
  $("#period-desc").textContent = s.days.length === 1 ? t("sum.oneDay", { day: NM.dayLabel(s.from), mon: dur(s.mon_s) }) :
    t("sum.range", { from: NM.date(s.from), to: NM.date(s.to - 1), mon: dur(s.mon_s) }) + (s.unmon_s > 60 ? t("sum.unmon", { d: dur(s.unmon_s) }) : "");

  // medidor
  const av = s.avail, C = 2 * Math.PI * 72;
  const col = av == null ? "var(--unknown)" : av >= 0.995 ? "var(--ok)" : av >= 0.98 ? "var(--warn)" : "var(--down)";
  const fg = $("#g-fg");
  fg.style.stroke = col;
  fg.setAttribute("stroke-dasharray", `${(av || 0) * C} ${C}`);
  $("#g-val").textContent = NM.pct(av, av != null && av < 0.9995 ? 2 : 1);
  $("#g-sub").textContent = av == null ? t("gauge.noData") : t("gauge.sub", { down: dur(s.down_s), mon: dur(s.mon_s) });

  const isp = s.causes.isp || { count: 0, down_s: 0 };
  $("#kgrid").innerHTML = [
    kpi("var(--down)", t("kpi.outages"), s.count, s.count ? t("kpi.short", { n: s.short }) : t("kpi.none")),
    kpi("var(--warn)", t("kpi.offline"), dur(s.down_s), s.count ? t("kpi.avg", { d: dur(s.avg) }) : "&nbsp;"),
    kpi("var(--accent-2)", t("kpi.longest"), s.longest ? dur(s.longest.dur) : "—", s.longest ? esc(NM.dt(s.longest.start)) : "&nbsp;"),
    kpi("var(--isp)", t("kpi.isp"), isp.count === 1 ? t("kpi.ispOne") : t("kpi.ispMany", { n: isp.count }), t("kpi.ispTotal", { d: dur(isp.down_s) }), t("kpi.ispTip")),
  ].join("");

  $("#timeline").innerHTML = NM.timelineHTML(s);
  renderHours();
  renderCauses();
  renderList();
}

function renderHours() {
  const s = S.sum;
  $("#hours").innerHTML = s.count ? NM.hoursHTML(s.hours, S.hourMetric) : `<div class="empty">${t("hours.none")}</div>`;
}

function renderCauses() {
  const s = S.sum, total = s.down_s || 1;
  const keys = Object.keys(CAUSES).filter((k) => s.causes[k]);
  if (!keys.length) { $("#causes").innerHTML = `<div class="empty">${t("causes.none")}</div>`; return; }
  $("#causes").innerHTML = `<div class="stack">${keys.map((k) => `<i style="width:${(s.causes[k].down_s / total) * 100}%;background:${CAUSES[k].color}" data-tip="${esc(`<b>${CAUSES[k].label}</b><br>${t("causes.share", { p: NM.pct(s.causes[k].down_s / total, 0) })}`)}"></i>`).join("")}</div>
    <div class="clist">${keys.map((k) => `<div class="crow"><i style="background:${CAUSES[k].color}"></i>
      <div><b>${CAUSES[k].label}</b><small>${CAUSES[k].desc}</small></div>
      <div class="num"><b>${s.causes[k].count}×</b><small>${dur(s.causes[k].down_s)}</small></div></div>`).join("")}</div>`;
}

function renderList() {
  const s = S.sum;
  const counts = { all: s.outages.length };
  s.outages.forEach((o) => { counts[o.cause] = (counts[o.cause] || 0) + 1; });
  $("#chips").innerHTML = [["all", t("list.all"), "var(--accent)"]].concat(Object.keys(CAUSES).filter((k) => counts[k]).map((k) => [k, CAUSES[k].label, CAUSES[k].color]))
    .map(([k, l, c]) => `<button data-v="${k}" class="${S.filter === k ? "on" : ""}" style="--c:${c}"><i></i>${l} ${counts[k] || 0}</button>`).join("");
  let list = s.outages.filter((o) => S.filter === "all" || o.cause === S.filter);
  list = list.slice().sort(S.sort === "long" ? (a, b) => b.dur - a.dur : (a, b) => b.start - a.start);
  const maxDur = Math.max(1, ...list.map((o) => o.dur));
  $("#list-desc").textContent = s.outages.length ? t("list.desc", { n: s.outages.length }) : t("list.descNone");
  if (!list.length) { $("#olist").innerHTML = `<div class="empty">${t("list.empty")}</div>`; return; }
  $("#olist").innerHTML = list.slice(0, S.limit).map((o) => {
    const c = cause(o.cause), sig = NM.signal(o.rssi);
    const ended = o.ended_by && o.ended_by !== "voltou" ? " · " + esc(NM.endedBy(o.ended_by)) : "";
    return `<div class="orow" data-start="${o.start}" style="--c:${c.color}"><i style="background:${c.color}"></i>
      <div><b>${esc(NM.dt(o.start))}</b>${o.ongoing ? `<span class="live">${t("list.live")}</span>` : ""}<small>${t("list.until", { t: o.ongoing ? t("list.now") : NM.time(o.end) })}${ended}</small></div>
      <div class="o-dur"><b>${dur(o.dur)}</b><u style="width:${(o.dur / maxDur) * 100}%"></u></div>
      <div class="o-cause"><b>${c.label}</b><small>${esc(o.network || "")}${o.rssi != null ? ` · ${Math.round(o.rssi)} dBm (${sig.label})` : ""}</small></div></div>`;
  }).join("") + (list.length > S.limit ? `<button class="btn more" id="more">${t("list.more", { n: Math.min(40, list.length - S.limit), r: list.length - S.limit })}</button>` : "");
  const more = $("#more");
  if (more) more.onclick = () => { S.limit += 40; renderList(); };
}

$("#chips").onclick = (e) => { const b = e.target.closest("button"); if (!b) return; S.filter = b.dataset.v; S.limit = 40; renderList(); };
$("#sort").onchange = (e) => { S.sort = e.target.value; renderList(); };
$("#timeline").onclick = (e) => {
  const el = e.target.closest(".s-out");
  if (!el) return;
  S.filter = "all"; S.sort = "recent"; $("#sort").value = "recent";
  const idx = S.sum.outages.slice().sort((a, b) => b.start - a.start).findIndex((o) => String(o.start) === el.dataset.start);
  if (idx >= S.limit) S.limit = idx + 10;
  renderList();
  const row = document.querySelector(`.orow[data-start="${el.dataset.start}"]`);
  if (row) { row.scrollIntoView({ behavior: "smooth", block: "center" }); row.classList.add("flash"); setTimeout(() => row.classList.remove("flash"), 1800); }
};

/* ---------- controles ---------- */
seg($("#series-seg"), S.seriesH, (v) => { S.seriesH = v; NM.store.set("series", v); loadSeries(); });
seg($("#hour-seg"), S.hourMetric, (v) => { S.hourMetric = v; renderHours(); });
seg($("#period-seg"), S.period, (v) => {
  S.period = v; NM.store.set("period", v);
  $("#custom").classList.toggle("on", v === "custom");
  if (v === "custom") {
    const r = S.custom || NM.rangeFor("7d");
    $("#d-from").value = r.from; $("#d-to").value = r.to;
  }
  S.limit = 40; loadSummary();
});
$("#custom").classList.toggle("on", S.period === "custom");
if (S.period === "custom" && S.custom) { $("#d-from").value = S.custom.from; $("#d-to").value = S.custom.to; }
$("#d-apply").onclick = () => {
  if (!$("#d-from").value || !$("#d-to").value) return;
  S.custom = { from: $("#d-from").value, to: $("#d-to").value }; NM.store.set("custom", S.custom); loadSummary();
};

/* ---------- atualizar agora ---------- */
$("#refresh").onclick = async () => {
  const b = $("#refresh");
  if (b.classList.contains("spin")) return;
  b.classList.add("spin");
  await Promise.all([pollStatus(), loadGlance(), loadSummary(), loadSeries(), new Promise((r) => setTimeout(r, 600))]);
  b.classList.remove("spin");
};

/* ---------- avisos ---------- */
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
    $("#topic").textContent = S.cfg.ntfy_topic || t("ntfy.disabled");
    $("#ntfy-step2").innerHTML = t("ntfy.step2", { server: esc(S.cfg.ntfy_server.replace(/^https?:\/\//, "")) });
    const addr = S.cfg.host ? `http://${S.cfg.host}:${S.cfg.port}` : "";
    renderPhone();
    renderPlanForm();
    // o plano chega com a configuração: redesenha o que compara com ele
    renderSpeedVals.html = null; renderSpeedVals(); renderSpeedChart(); renderSpeedDesc();
    $("#foot").innerHTML = esc(t("foot", { n: S.cfg.interval })) + (addr ? ` · <a href="${esc(addr)}">${esc(addr)}</a>` : "") + (S.cfg.ip ? ` · ${esc(S.cfg.ip)}` : "");
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
  box.innerHTML = (code ? `<div class="qr">${code}</div>` : "") + `<p>${t("phone.desc")}</p>` +
    `<p class="muted">${t("phone.or", { url: `<code>${esc(alt)}</code>` })}</p>`;
}

$("#install-x").onclick = () => { NM.store.set("installHidden", true); renderInstall(); };
$("#install-btn").onclick = promptInstall;
window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); installPrompt = e; renderInstall(); renderPhone(); });
window.addEventListener("appinstalled", () => { NM.store.set("installHidden", true); renderInstall(); });
renderInstall();
renderPhone();

let rT;
window.addEventListener("resize", () => { clearTimeout(rT); rT = setTimeout(() => { renderSeries(); renderSpeedChart(); }, 120); });

loadConfig();
pollStatus();
loadGlance();
loadSummary();
loadSeries();
setInterval(pollStatus, 3000);
setInterval(loadGlance, 30000);
setInterval(() => { renderHero(); if (S.gl) renderGlance(); }, 1000);
setInterval(loadSummary, 60000);
setInterval(loadSeries, 30000);
