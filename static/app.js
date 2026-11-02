"use strict";
const $ = (s) => document.querySelector(s);
const { esc, dur, cause, CAUSES } = NM;
const tips = NM.initTips();

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
  ["hour", "Pelo horário", `escuro das ${DARK_FROM}h às ${DARK_TO}h`],
  ["system", "Sistema", "segue o aparelho"],
  ["light", "Claro", ""],
  ["dark", "Escuro", ""],
];
const svg = (k) => `<svg viewBox="0 0 24 24">${ICONS[k]}</svg>`;
let theme = NM.store.get("tema", "hour");

function applyTheme() {
  let t = theme;
  if (t === "hour") { const h = new Date().getHours(); t = h >= DARK_FROM || h < DARK_TO ? "dark" : "light"; }
  if (t === "system") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t;
  const shown = t === "system" ? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light") : t;
  // ícone do botão = o que está na tela agora (sol/lua), ou relógio/tela quando é automático
  $("#theme").innerHTML = svg(theme === "hour" || theme === "system" ? theme : shown);
  $("#theme").title = "Tema: " + THEMES.find((x) => x[0] === theme)[1].toLowerCase();
  document.querySelector('meta[name="theme-color"]').content = shown === "dark" ? "#080c15" : "#f2f4f9";
  $("#theme-menu").innerHTML = THEMES.map(([k, l, h]) =>
    `<button role="menuitemradio" aria-checked="${k === theme}" data-v="${k}" class="${k === theme ? "on" : ""}">${svg(k)}<span>${l}${h ? `<small>${h}</small>` : ""}</span><span>${k === theme ? "✓" : ""}</span></button>`).join("");
}
const toggleMenu = (open) => { $("#theme-menu").classList.toggle("on", open); $("#theme").setAttribute("aria-expanded", open); };
$("#theme").onclick = (e) => { e.stopPropagation(); toggleMenu(!$("#theme-menu").classList.contains("on")); };
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
  if (!st) return { cls: "idle", title: "Sem contato com o monitor", lbl: "", big: "", sub: "O computador do monitor está ligado e na mesma rede que você?" };
  const now = nowS();
  if (st.last && now - st.last > Math.max(30, st.interval * 5))
    return { cls: "idle", title: "Monitor parado", lbl: "último teste", big: NM.time(st.last), sub: "O processo está rodando, mas os testes pararam." };
  if (st.state === "starting") return { cls: "idle", title: "Iniciando…", lbl: "", big: "", sub: "Fazendo os primeiros testes de conexão." };
  if (st.state === "down") {
    const c = cause(st.outage.cause);
    return { cls: "down", title: "Sem internet", lbl: "fora do ar há", big: NM.clock(now - st.outage.start),
      sub: `desde ${NM.time(st.outage.start)} · causa provável: <b>${esc(c.label)}</b>` };
  }
  if (st.pending) return { cls: "warn", title: "Instável", lbl: "online há", big: NM.clock(now - st.since),
    sub: `${st.pending} teste(s) falharam agora — confirmando se é queda…` };
  return { cls: "up", title: "Online", lbl: st.since_start ? "monitorando há" : "sem quedas há", big: NM.clock(now - st.since),
    sub: st.since_start ? `sem quedas desde que o monitor iniciou (${NM.dt(st.since)})` : `última queda terminou ${NM.dt(st.since)}` };
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
  document.title = (h.cls === "down" ? `Sem internet ${h.big}` : h.title) + " · down-again";
  if (renderHero.last !== h.cls) { favicon(color); renderHero.last = h.cls; }
}

function setNode(id, cls, text) { const n = $(id); n.className = "node " + cls; n.querySelector("small").textContent = text; }
function setLink(id, cls) { $(id).className = "link " + cls; }

function renderPath() {
  const st = S.st, p = st && st.probe, net = st && st.net;
  if (!p) { ["#n-mac", "#n-gw", "#n-net", "#n-web"].forEach((n) => setNode(n, "idle", "—")); ["#l-1", "#l-2", "#l-3"].forEach((l) => setLink(l, "idle")); return; }
  const hasNet = net && net.kind;
  const sig = NM.signal(net && net.rssi);
  setNode("#n-mac", hasNet ? "ok" : "bad", !hasNet ? "sem rede" : net.kind === "cabo" ? "via cabo" : (net.ssid || "Wi-Fi") + (sig.label ? ` · ${sig.label}` : ""));
  const gwOk = p.gw && p.gw_ms != null, gwState = !p.gw ? "bad" : gwOk ? "ok" : p.state === "local" ? "bad" : "unk";
  setLink("#l-1", gwState);
  setNode("#n-gw", gwState, !p.gw ? "inacessível" : gwOk ? NM.ms(p.gw_ms) : gwState === "unk" ? "não responde ping" : "sem resposta");
  const netOk = p.net_ms != null;
  setLink("#l-2", netOk ? "ok" : gwState === "bad" ? "idle" : "bad");
  setNode("#n-net", netOk ? "ok" : gwState === "bad" ? "idle" : "bad", netOk ? NM.ms(p.net_ms) : "sem resposta");
  setLink("#l-3", !netOk ? "idle" : p.http_ok ? "ok" : "bad");
  setNode("#n-web", !netOk ? "idle" : p.http_ok ? "ok" : "bad", !netOk ? "—" : p.http_ok ? "abrindo" : "não abrem");
  const notes = {
    ok: `Tudo respondendo. Teste a cada ${st.interval}s.`,
    isp: "O roteador responde, mas nada passa dele para fora: problema no provedor.",
    local: "O monitor não alcança o roteador: Wi-Fi, cabo ou o próprio roteador.",
    dns: "A internet responde por IP, mas os nomes não resolvem (DNS do provedor/roteador).",
    unknown: "Sem internet, e o roteador não responde a ping — não dá para dizer onde parou.",
  };
  $("#path-note").textContent = notes[p.state] || "";
}

function renderNet() {
  const net = S.st && S.st.net;
  if (!net || !net.kind) {
    $("#neticon").innerHTML = NM.wifiIcon(4, "off"); $("#netname").textContent = "Sem rede"; $("#netsub").textContent = ""; return;
  }
  if (net.kind === "cabo") {
    $("#neticon").innerHTML = `<svg class="wifi" viewBox="0 0 24 24"><path class="on" d="M9 3v4M15 3v4M7 7h10v5a5 5 0 0 1-10 0zM12 17v4"/></svg>`;
    $("#netname").textContent = "Cabo";
    $("#netsub").textContent = net.port || net.iface || "";
    // dataset recebe HTML pronto (não passa pelo parser): escapa só os valores vindos do sistema
    $("#netchip").dataset.tip = `<b>Conectado por cabo</b><br>${esc(net.port || "")} (${esc(net.iface || "")})`;
    return;
  }
  const sig = NM.signal(net.rssi);
  $("#neticon").innerHTML = NM.wifiIcon(net.rssi == null ? 4 : sig.bars);   // sem leitura de sinal: ícone cheio
  $("#netname").textContent = net.ssid || "Wi-Fi";
  $("#netsub").textContent = net.rssi != null ? `${Math.round(net.rssi)} dBm · ${sig.label}` : "";
  $("#netchip").dataset.tip = `<b>${esc(net.ssid || "Wi-Fi")}</b><br>` +
    [net.rssi != null && `sinal ${Math.round(net.rssi)} dBm (${sig.label})`, net.noise != null && `ruído ${Math.round(net.noise)} dBm`,
     net.channel && `canal ${esc(net.channel)}`, net.tx_rate && `link ${Math.round(net.tx_rate)} Mbps`].filter(Boolean).join("<br>");
}

async function pollStatus() {
  try {
    const st = await NM.get("/api/status");
    S.offset = st.now - Date.now() / 1000;
    const changed = !S.st || S.st.state !== st.state || (S.st.outage && S.st.outage.start) !== (st.outage && st.outage.start);
    S.st = st; S.failCount = 0;
    renderPath(); renderNet();
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
  $("#gl-title").textContent = h.count ? `${h.count} ${h.count === 1 ? "queda" : "quedas"} nas últimas 24h` : "Sem quedas nas últimas 24h";
  $("#gl-sub").textContent = last && last.ongoing ? "Caiu agora" :
    last ? `Última queda há ${dur(now - last.end)}` : young ? `Monitorando há ${dur(now - g.since)}` : "Nenhuma queda registrada";
  $("#glance").className = "card glance " + (h.count ? (last && last.ongoing ? "bad" : "warn") : "ok");
  $("#gl-ic").innerHTML = GL_ICONS[h.count ? "bad" : "ok"];
  const tile = (label, w, period) => `<${period ? `button data-p="${period}"` : "div"} class="gl-tile">
      <span>${label}</span><b class="${w.count ? "" : "z"}">${w.count}</b></${period ? "button" : "div"}>`;
  $("#gl-tiles").innerHTML = tile("24h", h) + tile("7 dias", g.d7, "7d") + tile("30 dias", g.d30, "30d");
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
  const X = (t) => L + ((t - d.from) / span) * (W - L - R);
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
    const t = d.from + (span / nT) * i;
    const lbl = span > 2 * 86400 ? NM.dayLabel(t) : NM.time(t, false);
    g += `<text class="ax" x="${X(t)}" y="${H - 5}" text-anchor="${i === 0 ? "start" : i === nT ? "end" : "middle"}">${lbl}</text>`;
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
    pts.forEach((p, i) => {
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
  if (!pts.length) box.insertAdjacentHTML("beforeend", `<div class="empty" style="position:absolute;inset:0;display:grid;place-items:center"><span>Ainda sem dados neste intervalo.</span></div>`);
  const ov = box.querySelector("#ov"), xh = box.querySelector("#xh"), xd = box.querySelector("#xd");
  const move = (cx, cy) => {
    if (!pts.length) return;
    const r = box.getBoundingClientRect(), x = cx - r.left;
    const t = d.from + ((x - L) / (W - L - R)) * span;
    let best = pts[0];
    for (const p of pts) if (Math.abs(p.t - t) < Math.abs(best.t - t)) best = p;
    const px = X(best.t + d.step / 2);
    xh.setAttribute("x1", px); xh.setAttribute("x2", px);
    xd.setAttribute("cx", px); xd.setAttribute("cy", best.avg != null ? Y(best.avg) : Y(0));
    box.classList.add("hover");
    const sig = NM.signal(best.rssi);
    tips.show(cx, cy, `<b>${span > 86400 ? NM.dt(best.t) : NM.time(best.t, false)}</b>` +
      `<br>internet: ${NM.ms(best.avg)}` +
      `<br>roteador: ${NM.ms(best.gw)}` +
      (best.fail ? `<br><span style="color:#ff8a80">${best.fail} de ${best.n} testes falharam</span>` : "") +
      (best.rssi != null ? `<br><span class="tip-m">sinal ${Math.round(best.rssi)} dBm · ${sig.label}</span>` : ""));
  };
  ov.addEventListener("mousemove", (e) => move(e.clientX, e.clientY));
  ov.addEventListener("touchmove", (e) => { move(e.touches[0].clientX, e.touches[0].clientY); }, { passive: true });
  ov.addEventListener("touchstart", (e) => { move(e.touches[0].clientX, e.touches[0].clientY); }, { passive: true });
  ov.addEventListener("mouseleave", () => { box.classList.remove("hover"); tips.hide(); });
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
  $("#lnk-csv").href = "/api/outages.csv?" + qs;
  try { S.sum = await NM.get("/api/summary?" + qs); renderSummary(); } catch (e) { /* mantém o último */ }
}

function kpi(color, title, value, sub, tip) {
  return `<div class="card kpi" style="--c:${color}" ${tip ? `data-tip="${esc(tip)}"` : ""}><h3><i></i>${title}</h3><b>${value}</b><small>${sub}</small></div>`;
}

function renderSummary() {
  const s = S.sum;
  const days = s.days.length;
  $("#period-desc").textContent = days === 1 ? `${NM.dayLabel(s.from)} · ${dur(s.mon_s)} monitorados` :
    `${NM.date(s.from)} a ${NM.date(s.to - 1)} · ${dur(s.mon_s)} monitorados` + (s.unmon_s > 60 ? ` · ${dur(s.unmon_s)} sem monitorar` : "");

  // medidor
  const av = s.avail, C = 2 * Math.PI * 72;
  const col = av == null ? "var(--unknown)" : av >= 0.995 ? "var(--ok)" : av >= 0.98 ? "var(--warn)" : "var(--down)";
  const fg = $("#g-fg");
  fg.style.stroke = col;
  fg.setAttribute("stroke-dasharray", `${(av || 0) * C} ${C}`);
  $("#g-val").textContent = NM.pct(av, av != null && av < 0.9995 ? 2 : 1);
  $("#g-sub").innerHTML = av == null ? "Sem dados ainda" : `${esc(dur(s.down_s))} sem internet em ${esc(dur(s.mon_s))}`;

  const isp = s.causes.isp || { count: 0, down_s: 0 };
  $("#kgrid").innerHTML = [
    kpi("var(--down)", "Quedas", s.count, s.count ? `${s.short} curtas (< 1 min)` : "nenhuma no período"),
    kpi("var(--warn)", "Tempo sem internet", dur(s.down_s), s.count ? `média de ${dur(s.avg)} por queda` : "&nbsp;"),
    kpi("var(--accent-2)", "Maior queda", s.longest ? dur(s.longest.dur) : "—", s.longest ? NM.dt(s.longest.start) : "&nbsp;"),
    kpi("var(--isp)", "Culpa do provedor", isp.count + (isp.count === 1 ? " queda" : " quedas"), `${dur(isp.down_s)} no total`,
      "Quedas em que o roteador respondia normalmente e a internet não."),
  ].join("");

  $("#timeline").innerHTML = NM.timelineHTML(s);
  renderHours();
  renderCauses();
  renderList();
}

function renderHours() {
  const s = S.sum;
  $("#hours").innerHTML = s.count ? NM.hoursHTML(s.hours, S.hourMetric) : `<div class="empty"><b>Nenhuma queda</b>Sem padrão de horário para mostrar.</div>`;
}

function renderCauses() {
  const s = S.sum, total = s.down_s || 1;
  const keys = Object.keys(CAUSES).filter((k) => s.causes[k]);
  if (!keys.length) { $("#causes").innerHTML = `<div class="empty"><b>Nada a apontar</b>Nenhuma queda no período.</div>`; return; }
  $("#causes").innerHTML = `<div class="stack">${keys.map((k) => `<i style="width:${(s.causes[k].down_s / total) * 100}%;background:${CAUSES[k].color}" data-tip="${esc(`<b>${CAUSES[k].label}</b><br>${NM.pct(s.causes[k].down_s / total, 0)} do tempo sem internet`)}"></i>`).join("")}</div>
    <div class="clist">${keys.map((k) => `<div class="crow"><i style="background:${CAUSES[k].color}"></i>
      <div><b>${CAUSES[k].label}</b><small>${CAUSES[k].desc}</small></div>
      <div class="num"><b>${s.causes[k].count}×</b><small>${dur(s.causes[k].down_s)}</small></div></div>`).join("")}</div>`;
}

function renderList() {
  const s = S.sum;
  const counts = { all: s.outages.length };
  s.outages.forEach((o) => { counts[o.cause] = (counts[o.cause] || 0) + 1; });
  $("#chips").innerHTML = [["all", "Todas", "var(--accent)"]].concat(Object.keys(CAUSES).filter((k) => counts[k]).map((k) => [k, CAUSES[k].label, CAUSES[k].color]))
    .map(([k, l, c]) => `<button data-v="${k}" class="${S.filter === k ? "on" : ""}" style="--c:${c}"><i></i>${l} ${counts[k] || 0}</button>`).join("");
  let list = s.outages.filter((o) => S.filter === "all" || o.cause === S.filter);
  list = list.slice().sort(S.sort === "long" ? (a, b) => b.dur - a.dur : (a, b) => b.start - a.start);
  const maxDur = Math.max(1, ...list.map((o) => o.dur));
  $("#list-desc").textContent = s.outages.length ? `${s.outages.length} no período · clique numa queda na linha do tempo para achá-la aqui` : "Nenhuma queda no período";
  if (!list.length) { $("#olist").innerHTML = `<div class="empty"><b>🎉 Nenhuma queda</b>A conexão ficou de pé o período todo.</div>`; return; }
  $("#olist").innerHTML = list.slice(0, S.limit).map((o) => {
    const c = cause(o.cause), sig = NM.signal(o.rssi);
    return `<div class="orow" data-start="${o.start}" style="--c:${c.color}"><i style="background:${c.color}"></i>
      <div><b>${NM.dt(o.start)}</b>${o.ongoing ? `<span class="live">AO VIVO</span>` : ""}<small>até ${o.ongoing ? "agora" : NM.time(o.end)}${o.ended_by && o.ended_by !== "voltou" ? " · " + esc(o.ended_by) : ""}</small></div>
      <div class="o-dur"><b>${dur(o.dur)}</b><u style="width:${(o.dur / maxDur) * 100}%"></u></div>
      <div class="o-cause"><b>${c.label}</b><small>${esc(o.network || "")}${o.rssi != null ? ` · ${Math.round(o.rssi)} dBm (${sig.label})` : ""}</small></div></div>`;
  }).join("") + (list.length > S.limit ? `<button class="btn more" id="more">Mostrar mais ${Math.min(40, list.length - S.limit)} de ${list.length - S.limit}</button>` : "");
  const more = $("#more");
  if (more) more.onclick = () => { S.limit += 40; renderList(); };
}

$("#chips").onclick = (e) => { const b = e.target.closest("button"); if (!b) return; S.filter = b.dataset.v; S.limit = 40; renderList(); };
$("#sort").onchange = (e) => { S.sort = e.target.value; renderList(); };
$("#timeline").onclick = (e) => {
  const seg = e.target.closest(".s-out");
  if (!seg) return;
  S.filter = "all"; S.sort = "recent"; $("#sort").value = "recent";
  const idx = S.sum.outages.slice().sort((a, b) => b.start - a.start).findIndex((o) => String(o.start) === seg.dataset.start);
  if (idx >= S.limit) S.limit = idx + 10;
  renderList();
  const row = document.querySelector(`.orow[data-start="${seg.dataset.start}"]`);
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
  const t = $("#topic").textContent;
  try { await navigator.clipboard.writeText(t); $("#copy").textContent = "Copiado ✓"; }
  catch (e) { const r = document.createRange(); r.selectNodeContents($("#topic")); const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r); $("#copy").textContent = "Selecionado"; }
  setTimeout(() => { $("#copy").textContent = "Copiar"; }, 1600);
};
$("#test").onclick = async () => {
  const res = $("#test-res");
  res.className = "res"; res.textContent = "enviando…";
  try {
    // fetch direto: respostas 403/429 também trazem a mensagem de erro em JSON
    const r = await (await fetch("/api/test-notify", { method: "POST", headers: { "X-Down-Again": "1" } })).json();
    res.className = "res " + (r.ok ? "ok" : "bad");
    res.textContent = r.ok ? "Enviado! Confira o celular." : "Falhou: " + (r.error || "erro");
  } catch (e) { res.className = "res bad"; res.textContent = "Sem contato com o monitor"; }
};

async function loadConfig() {
  try {
    S.cfg = await NM.get("/api/config");
    $("#topic").textContent = S.cfg.ntfy_topic || "(desativado em dados/config.json)";
    $("#ntfy-srv").textContent = S.cfg.ntfy_server.replace(/^https?:\/\//, "");
    $("#n-mac-label").textContent = S.cfg.platform === "macOS" ? "Este Mac" : "Este PC";
    const addr = S.cfg.host ? `http://${S.cfg.host}:${S.cfg.port}` : "";
    $("#foot").innerHTML = `down-again · teste a cada ${S.cfg.interval}s` + (addr ? ` · <a href="${esc(addr)}">${esc(addr)}</a>` : "") + (S.cfg.ip ? ` · ${esc(S.cfg.ip)}` : "");
  } catch (e) { setTimeout(loadConfig, 5000); }
}

let rT;
window.addEventListener("resize", () => { clearTimeout(rT); rT = setTimeout(renderSeries, 120); });

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
