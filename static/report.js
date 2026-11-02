"use strict";
const $ = (s) => document.querySelector(s);
const { esc, dur, cause, CAUSES } = NM;
NM.initTips();

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
$("#apply").onclick =() => { history.replaceState(null, "", `?from=${$("#d-from").value}&to=${$("#d-to").value}`); load(); };

async function load() {
  const qs = `from=${$("#d-from").value}&to=${$("#d-to").value}`;
  $("#csv").href = "/api/outages.csv?" + qs;
  const [s, cfg] = await Promise.all([NM.get("/api/summary?" + qs), NM.get("/api/config")]);
  render(s, cfg);
}

function render(s, cfg) {
  const isp = s.causes.isp || { count: 0, down_s: 0 };
  const lat = s.latency;
  const period = `${NM.date(s.from)} a ${NM.date(s.to - 1)}`;
  $("#lead").textContent = `Período analisado: ${period}. Medições automáticas feitas por um computador ligado à rede do endereço abaixo.`;
  document.title = `Relatório de disponibilidade — ${period}`;

  const rows = [
    ["Período analisado", period],
    ["Tempo efetivamente monitorado", dur(s.mon_s)],
    ["Tempo não monitorado (computador desligado/sem energia)", dur(s.unmon_s)],
    ["Disponibilidade medida", NM.pct(s.avail, 3)],
    ["Número de interrupções", `${s.count}` + (s.short ? ` (${s.short} com menos de 1 minuto)` : "")],
    ["Tempo total sem acesso à internet", dur(s.down_s)],
    ["Duração média / mediana", s.count ? `${dur(s.avg)} / ${dur(s.median)}` : "—"],
    ["Maior interrupção", s.longest ? `${dur(s.longest.dur)} — em ${NM.dtFull(s.longest.start)}` : "—"],
    ["Interrupções atribuídas ao provedor", `${isp.count} (${dur(isp.down_s)})`],
    ["Intervalo médio entre interrupções", s.mtbf ? dur(s.mtbf) : "—"],
    ["Latência (mediana / 95º percentil)", lat ? `${NM.ms(lat.p50)} / ${NM.ms(lat.p95)}` : "—"],
    ["Testes realizados / com falha", `${NM.num(s.samples)} / ${NM.pct(s.fail_pct, 2)}`],
  ];
  let html = `<table class="sum">${rows.map(([a, b]) => `<tr><td>${a}</td><td>${esc(b)}</td></tr>`).join("")}</table>`;
  if (s.count) {
    html += `<div class="hl">No período, foram registradas <b>${s.count} interrupções</b>, somando <b>${dur(s.down_s)}</b> sem acesso à internet
      (disponibilidade medida de ${NM.pct(s.avail, 3)}). Em <b>${isp.count}</b> delas (${dur(isp.down_s)}), o roteador da residência respondia
      normalmente enquanto nenhum dos servidores externos testados respondia, o que indica falha no serviço do provedor e não na rede interna.</div>`;
  }
  $("#summary").innerHTML = html;

  $("#meth").innerHTML = [
    `Um computador dedicado ficou ligado à rede do endereço e executou um teste a cada <b>${cfg.interval} segundos</b>, com tempo limite de ${cfg.timeout}s por verificação.`,
    `Cada teste verifica três pontos: (1) o roteador local, por ping; (2) a internet por endereço IP, abrindo conexão com servidores independentes (${cfg.tcp_targets.map(esc).join(", ")}) — basta um responder; (3) a abertura de uma página por nome (${esc(cfg.http_url)}), que depende de DNS.`,
    `Uma interrupção é registrada após <b>${cfg.fail_threshold} testes seguidos com falha</b>; o início considerado é o do primeiro teste que falhou, e o fim é o primeiro teste bem-sucedido. Falhas isoladas não são contadas como interrupção.`,
    `Causa provável: <b>Provedor</b> quando o roteador responde mas a internet não; <b>Rede local</b> quando o roteador não responde; <b>DNS</b> quando a internet responde por IP mas as páginas não abrem; <b>Indeterminada</b> quando o roteador não responde a ping.`,
    `Períodos em que o computador esteve desligado, em repouso ou sem energia foram excluídos do cálculo e aparecem listados como “não monitorados”. Disponibilidade = (tempo monitorado − tempo sem internet) ÷ tempo monitorado.`,
  ].map((x) => `<li>${x}</li>`).join("");

  $("#timeline").innerHTML = NM.timelineHTML(s, { newestFirst: false });

  $("#days").innerHTML = `<table><tr><th>Dia</th><th class="n">Monitorado</th><th class="n">Quedas</th><th class="n">Provedor</th><th class="n">Sem internet</th><th class="n">Disponibilidade</th></tr>
    ${s.days.filter((d) => d.mon_s > 0).map((d) => `<tr><td>${NM.dayLabel(d.start)}/${new Date(d.start * 1000).getFullYear()}</td><td class="n">${dur(d.mon_s)}</td>
      <td class="n">${d.count}</td><td class="n">${d.isp}</td><td class="n">${dur(d.down_s)}</td><td class="n">${NM.pct(d.avail, 2)}</td></tr>`).join("")}</table>`;

  $("#hours").innerHTML = s.count ? NM.hoursHTML(s.hours, "count") : `<p class="muted2">Nenhuma queda no período.</p>`;

  $("#list").innerHTML = s.outages.length ? `<table><tr><th>#</th><th>Início</th><th>Fim</th><th class="n">Duração</th><th>Causa provável</th><th>Rede</th></tr>
    ${s.outages.map((o, i) => `<tr><td>${i + 1}</td><td>${NM.dtFull(o.start)}</td><td>${o.ongoing ? "em andamento" : NM.dtFull(o.end)}</td>
      <td class="n">${dur(o.dur)}</td><td><span class="dot" style="background:${cause(o.cause).color}"></span>${cause(o.cause).label}${o.ended_by && o.ended_by !== "voltou" ? ` <span class="muted2">(${esc(o.ended_by)})</span>` : ""}</td>
      <td>${esc(o.network || "")}</td></tr>`).join("")}</table>` : `<p class="muted2">Nenhuma interrupção registrada no período.</p>`;

  $("#unmon").innerHTML = s.unmonitored.length ? `<table><tr><th>De</th><th>Até</th><th class="n">Duração</th></tr>
    ${s.unmonitored.map(([a, b]) => `<tr><td>${NM.dtFull(a)}</td><td>${NM.dtFull(b)}</td><td class="n">${dur(b - a)}</td></tr>`).join("")}</table>`
    : `<p class="muted2">Nenhum — o monitoramento foi contínuo no período.</p>`;

  $("#foot").textContent = `Gerado em ${NM.dtFull(s.now)} pelo monitor down-again` + (cfg.host ? ` (${cfg.host})` : "") +
    `. Os dados brutos de cada interrupção estão disponíveis em planilha (CSV).`;
}

load().catch(() => { $("#lead").textContent = "Não foi possível falar com o monitor."; });
