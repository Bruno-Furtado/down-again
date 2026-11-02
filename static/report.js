"use strict";
const $ = (s) => document.querySelector(s);
const { esc, dur, cause, t } = NM;
NM.initTips();
NM.applyStatic();
NM.mountLangMenu($("#lang"), $("#lang-menu"));
document.title = t("r.pageTitle");

// identificação editável, salva localmente
const ident = NM.store.get("ident", {});
document.querySelectorAll("#ident input").forEach((i) => {
  i.value = ident[i.dataset.k] || "";
  i.oninput = () => { ident[i.dataset.k] = i.value; NM.store.set("ident", ident); };
});

const q = new URLSearchParams(location.search);
const def = NM.rangeFor("30d");
$("#d-from").value = q.get("from") || def.from;
$("#d-to").value = q.get("to") || def.to;
$("#print").onclick = () => window.print();
$("#apply").onclick = () => { history.replaceState(null, "", `?from=${$("#d-from").value}&to=${$("#d-to").value}`); load(); };

async function load() {
  const qs = `from=${$("#d-from").value}&to=${$("#d-to").value}`;
  $("#csv").href = `/api/outages.csv?${qs}&lang=${NM.lang}`;
  const [s, cfg, sp] = await Promise.all([NM.get("/api/summary?" + qs), NM.get("/api/config"), NM.get("/api/speedtests?" + qs)]);
  render(s, cfg);
  renderSpeed(sp);
}

function render(s, cfg) {
  const isp = s.causes.isp || { count: 0, down_s: 0 };
  const lat = s.latency;
  const period = t("r.periodRange", { a: NM.date(s.from), b: NM.date(s.to - 1) });
  $("#lead").textContent = t("r.lead", { p: period });
  document.title = t("r.docTitle", { p: period });

  const rows = [
    [t("r.period"), period],
    [t("r.monitored"), dur(s.mon_s)],
    [t("r.unmonitored"), dur(s.unmon_s)],
    [t("r.avail"), NM.pct(s.avail, 3)],
    [t("r.count"), s.short ? t("r.countShort", { n: s.count, s: s.short }) : String(s.count)],
    [t("r.offline"), dur(s.down_s)],
    [t("r.avgMedian"), s.count ? `${dur(s.avg)} / ${dur(s.median)}` : "—"],
    [t("r.longest"), s.longest ? t("r.longestVal", { d: dur(s.longest.dur), dt: NM.dtFull(s.longest.start) }) : "—"],
    [t("r.ispCount"), `${isp.count} (${dur(isp.down_s)})`],
    [t("r.mtbf"), s.mtbf ? dur(s.mtbf) : "—"],
    [t("r.latency"), lat ? `${NM.ms(lat.p50)} / ${NM.ms(lat.p95)}` : "—"],
    [t("r.checks"), `${NM.num(s.samples)} / ${NM.pct(s.fail_pct, 2)}`],
  ];
  let html = `<table class="sum">${rows.map(([a, b]) => `<tr><td>${a}</td><td>${esc(b)}</td></tr>`).join("")}</table>`;
  if (s.count) {
    html += `<div class="hl">${t("r.highlight", { n: s.count, down: dur(s.down_s), avail: NM.pct(s.avail, 3), isp: isp.count, ispDown: dur(isp.down_s) })}</div>`;
  }
  $("#summary").innerHTML = html;

  const vars = { interval: cfg.interval, timeout: cfg.timeout, threshold: cfg.fail_threshold,
    targets: cfg.tcp_targets.map(esc).join(", "), url: esc(cfg.http_url) };
  $("#meth").innerHTML = ["r.m1", "r.m2", "r.m3", "r.m4", "r.m5"].map((k) => `<li>${t(k, vars)}</li>`).join("");

  $("#timeline").innerHTML = NM.timelineHTML(s, { newestFirst: false });

  $("#days").innerHTML = `<table><tr><th>${t("r.th.day")}</th><th class="n">${t("r.th.monitored")}</th><th class="n">${t("r.th.outages")}</th>
    <th class="n">${t("r.th.isp")}</th><th class="n">${t("r.th.offline")}</th><th class="n">${t("r.th.avail")}</th></tr>
    ${s.days.filter((d) => d.mon_s > 0).map((d) => `<tr><td>${esc(NM.dayFull(d.start))}</td><td class="n">${dur(d.mon_s)}</td>
      <td class="n">${d.count}</td><td class="n">${d.isp}</td><td class="n">${dur(d.down_s)}</td><td class="n">${NM.pct(d.avail, 2)}</td></tr>`).join("")}</table>`;

  $("#hours").innerHTML = s.count ? NM.hoursHTML(s.hours, "count") : `<p class="muted2">${t("r.noneInPeriod")}</p>`;

  $("#list").innerHTML = s.outages.length ? `<table><tr><th>#</th><th>${t("r.th.start")}</th><th>${t("r.th.end")}</th><th class="n">${t("r.th.dur")}</th>
    <th>${t("r.th.cause")}</th><th>${t("r.th.network")}</th></tr>
    ${s.outages.map((o, i) => `<tr><td>${i + 1}</td><td>${NM.dtFull(o.start)}</td><td>${o.ongoing ? t("r.ongoing") : NM.dtFull(o.end)}</td>
      <td class="n">${dur(o.dur)}</td><td><span class="dot" style="background:${cause(o.cause).color}"></span>${cause(o.cause).label}${o.ended_by && o.ended_by !== "voltou" ? ` <span class="muted2">(${esc(NM.endedBy(o.ended_by))})</span>` : ""}</td>
      <td>${esc(o.network || "")}</td></tr>`).join("")}</table>` : `<p class="muted2">${t("r.noOutages")}</p>`;

  $("#unmon").innerHTML = s.unmonitored.length ? `<table><tr><th>${t("r.th.from")}</th><th>${t("r.th.to")}</th><th class="n">${t("r.th.dur")}</th></tr>
    ${s.unmonitored.map(([a, b]) => `<tr><td>${NM.dtFull(a)}</td><td>${NM.dtFull(b)}</td><td class="n">${dur(b - a)}</td></tr>`).join("")}</table>`
    : `<p class="muted2">${t("r.unmonNone")}</p>`;

  $("#foot").textContent = t("r.footer", { dt: NM.dtFull(s.now), host: cfg.host ? ` (${cfg.host})` : "" });
}

// velocidade: médias, mínimos e comparação com o plano contratado
function renderSpeed(sp) {
  const mb = (v) => (v == null ? "—" : `${NM.num(v, v < 10 ? 1 : 0)} Mbps`);
  const ofPlan = (v, plan) => (plan && v != null ? t("r.speedPct", { v: mb(v), p: NM.pct(v / plan, 0) }) : mb(v));
  $("#speed-wrap").hidden = !sp.count && !sp.minutes;
  if (!sp.count) { $("#speed").innerHTML = `<p class="muted2">${t("r.speedNone")}</p>`; return; }
  const plan = sp.plan, rows = [
    [t("r.speedTests"), String(sp.count)],
    [t("r.speedDown"), `${ofPlan(sp.down.avg, plan.down)} / ${ofPlan(sp.down.min, plan.down)}`],
    [t("r.speedUp"), sp.up ? `${ofPlan(sp.up.avg, plan.up)} / ${ofPlan(sp.up.min, plan.up)}` : "—"],
    [t("r.speedPing"), sp.ping ? NM.ms(sp.ping.avg) : "—"],
  ];
  if (plan.down) rows.push([t("r.speedPlan"), `${mb(plan.down)} / ${mb(plan.up || null)}`], [t("r.speedBelow"), String(sp.below40)]);
  let html = `<table class="sum">${rows.map(([a, b]) => `<tr><td>${a}</td><td>${esc(b)}</td></tr>`).join("")}</table>`;
  if (plan.down) html += `<div class="hl">${t("r.speedHl", { avg: mb(sp.down.avg), pct: NM.pct(sp.down.avg / plan.down, 0), plan: mb(plan.down), n: sp.below40 })}</div>`;
  $("#speed").innerHTML = html;
  if (sp.minutes) {
    $("#meth").insertAdjacentHTML("beforeend", `<li>${t("r.m6", { minutes: sp.minutes, streams: sp.streams, server: esc(sp.server), seconds: sp.seconds })}</li>`);
  }
}

load().catch(() => { $("#lead").textContent = t("r.noContact"); });
