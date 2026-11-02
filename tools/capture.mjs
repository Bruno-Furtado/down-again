// Regera as imagens de docs/ (capa, prints e GIF) a partir do painel de demonstração.
// Requer Google Chrome e ffmpeg. Sem dependências npm (usa o WebSocket nativo do Node 22+).
//
//   python3 tools/demo.py          # em outro terminal (porta 8766)
//   node tools/capture.mjs         # tudo; ou: node tools/capture.mjs shots|gif|cover
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const TOOLS = path.dirname(fileURLToPath(import.meta.url));
const DOCS = path.join(TOOLS, "..", "docs");
const WORK = path.join(os.tmpdir(), "down-again-capture");
const MODE = process.argv[2] || "all";
const BASE = "http://localhost:" + (process.env.PORT || "8766");
const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
fs.mkdirSync(DOCS, { recursive: true });
fs.mkdirSync(WORK, { recursive: true });

const chrome = spawn(CHROME, ["--headless=new", "--remote-debugging-port=9333", `--user-data-dir=${path.join(WORK, "chrome-prof")}`,
  "--hide-scrollbars", "--no-first-run", "--no-default-browser-check", "--force-color-profile=srgb", "about:blank"], { stdio: "ignore" });
let targets = [];
for (let i = 0; i < 60 && !targets.length; i++) {
  try { targets = (await (await fetch("http://127.0.0.1:9333/json/list")).json()).filter((t) => t.type === "page"); } catch (e) { /* subindo */ }
  if (!targets.length) await sleep(250);
}
const ws = new WebSocket(targets[0].webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let seq = 0;
const pending = new Map(), listeners = [];
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); }
  else if (m.method) listeners.slice().forEach((l) => l(m));
};
const send = (method, params = {}) => new Promise((res, rej) => { const id = ++seq; pending.set(id, { res, rej }); ws.send(JSON.stringify({ id, method, params })); });
const once = (name) => new Promise((r) => { const l = (m) => { if (m.method === name) { listeners.splice(listeners.indexOf(l), 1); r(m.params); } }; listeners.push(l); });
const js = async (expression) => {
  const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception ? r.exceptionDetails.exception.description : JSON.stringify(r.exceptionDetails));
  return r.result.value;
};
await send("Page.enable");
await send("Runtime.enable");

const viewport = (width, height, scale, mobile = false) => send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: scale, mobile });
async function go(url, prefs = {}, wait = 2500) {
  let l = once("Page.loadEventFired");
  await send("Page.navigate", { url });
  await l;
  await js(`(() => { localStorage.clear(); const p = ${JSON.stringify(prefs)}; for (const k in p) localStorage.setItem("nm_" + k, JSON.stringify(p[k])); })()`);
  l = once("Page.loadEventFired");
  await send("Page.reload");
  await l;
  await sleep(wait);
}
async function shot(file, clip) {
  const r = await send("Page.captureScreenshot", Object.assign({ format: "png" }, clip ? { clip: Object.assign({ scale: 1 }, clip), captureBeyondViewport: true } : {}));
  fs.writeFileSync(file, Buffer.from(r.data, "base64"));
  console.log("ok", path.basename(file));
}
const rect = (sel) => js(`(() => { const r = document.querySelector(${JSON.stringify(sel)}).getBoundingClientRect(); return { x: r.left + scrollX, y: r.top + scrollY, width: r.width, height: r.height }; })()`);

const PREFS = { period: "7d", series: "24" };

if (MODE === "all" || MODE === "shots") {
  // desktop escuro e claro (topo)
  await viewport(1280, 860, 2);
  await go(BASE + "/", Object.assign({ tema: "dark" }, PREFS));
  await shot(path.join(DOCS, "dashboard-dark.png"));
  await go(BASE + "/", Object.assign({ tema: "light" }, PREFS));
  await shot(path.join(DOCS, "dashboard-light.png"));

  // análises: linha do tempo + horários + causas, com tooltip aberto numa queda
  const tl = await rect("#timeline"), causes = await rect("#row2");
  await js(`scrollTo(0, ${tl.y - 120})`);
  await sleep(300);
  const seg = await js(`(() => { const s = [...document.querySelectorAll(".s-out")].sort((a, b) => b.getBoundingClientRect().width - a.getBoundingClientRect().width)[0]; const r = s.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()`);
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: seg.x, y: seg.y });
  await sleep(300);
  const top = tl.y - 70;
  await shot(path.join(DOCS, "insights.png"), { x: 0, y: top, width: 1280, height: causes.y + causes.height - top + 20 });
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: 5, y: 5 });

  // celular claro e escuro
  await viewport(390, 844, 3, true);
  for (const tema of ["light", "dark"]) {
    await go(BASE + "/", Object.assign({ tema }, PREFS));
    await shot(path.join(WORK, `mobile-${tema}.png`));
  }

  // relatório
  await viewport(1000, 1250, 2);
  await go(BASE + "/relatorio?from=2026-10-27&to=2026-11-02", {}, 2000);
  await js(`(() => { const v = { titular: "Maria Exemplo", provedor: "Operadora X", endereco: "Rua Exemplo, 123 — São Paulo/SP", plano: "500 Mbps fibra", cliente: "000123456", protocolos: "2026110100123, 2026110200456" }; document.querySelectorAll("#ident input").forEach((i) => { i.value = v[i.dataset.k] || ""; }); })()`);
  await js(`scrollTo(0, 0)`);
  await shot(path.join(DOCS, "report.png"), { x: 0, y: 60, width: 1000, height: 1180 });
}

if (MODE === "all" || MODE === "gif") {
  const frames = path.join(WORK, "frames");
  fs.rmSync(frames, { recursive: true, force: true });
  fs.mkdirSync(frames);
  let n = 0;
  const frame = async () => { const r = await send("Page.captureScreenshot", { format: "png" }); fs.writeFileSync(path.join(frames, `f${String(n++).padStart(4, "0")}.png`), Buffer.from(r.data, "base64")); };
  const hold = async (count, each) => { for (let i = 0; i < count; i++) { if (each) await js(each); await frame(); } };

  await viewport(390, 844, 2, true);
  await go(BASE + "/", Object.assign({ tema: "light" }, PREFS), 3000);
  // congela os timers da página e passa a dirigir o estado quadro a quadro
  await js(`(() => {
    for (let i = 1; i < 10000; i++) clearInterval(i);
    window.__d = {
      keep(dt) { S.offset += dt || 0; S.st.last = nowS(); renderHero(); renderGlance(); },
      pending() { S.st = Object.assign({}, S.st, { pending: 1, last: nowS(), probe: Object.assign({}, S.st.probe, { state: "isp", net_ms: null, http_ok: false }) }); renderPath(); renderHero(); },
      down() {
        const n = nowS();
        S.st = Object.assign({}, S.st, { state: "down", pending: 0, last: n, outage: { start: n - 1, cause: "isp" },
          probe: { state: "isp", gw: "192.168.0.1", gw_ms: 3.1, net_ms: null, http_ok: false } });
        renderPath(); renderHero();
        ["h24", "d7", "d30"].forEach((k) => { S.gl[k].count += 1; });
        S.gl.now = n; S.gl.last = { start: n - 1, end: n, cause: "isp", ongoing: true }; renderGlance();
      },
      tick(sec) { S.st.outage.start -= sec; S.st.last = nowS(); renderHero(); },
      up() {
        const n = nowS();
        S.gl.now = n; S.gl.last = { start: S.st.outage.start, end: n, cause: "isp", ongoing: false };
        S.st = Object.assign({}, S.st, { state: "up", pending: 0, since: n, since_start: false, outage: null, last: n,
          probe: { state: "ok", gw: "192.168.0.1", gw_ms: 3.4, net_ms: 18, http_ok: true } });
        renderPath(); renderHero(); renderGlance();
      },
    };
  })()`);
  await hold(12, "__d.keep(1)");                 // online, cronômetro correndo
  await js("__d.pending()");
  await hold(9, "__d.keep(1)");                  // instável
  await js("__d.down()");
  for (let i = 0; i < 30; i++) { await js("__d.tick(7)"); await frame(); }   // sem internet (avanço rápido)
  await js("__d.up()");
  await hold(14, "__d.keep(1)");                 // voltou
  // rolagem até a linha do tempo e de volta
  const tl = await rect("#timeline");
  const target = tl.y - 90, ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
  for (let i = 1; i <= 22; i++) { await js(`scrollTo(0, ${Math.round(target * ease(i / 22))})`); await frame(); }
  await hold(12);
  const hrs = await rect("#hours");
  const t2 = hrs.y - 90;
  for (let i = 1; i <= 14; i++) { await js(`scrollTo(0, ${Math.round(target + (t2 - target) * ease(i / 14))})`); await frame(); }
  await hold(12);
  for (let i = 1; i <= 16; i++) { await js(`scrollTo(0, ${Math.round(t2 * (1 - ease(i / 16)))})`); await frame(); }
  await hold(4, "__d.keep(1)");
  // menu de tema → escuro
  await js(`document.querySelector("#theme").click()`);
  await hold(9, "__d.keep(1)");
  await js(`document.querySelector('#theme-menu [data-v="dark"]').click()`);
  await hold(16, "__d.keep(1)");
  console.log("frames", n);
  const enc = spawnSync("ffmpeg", ["-v", "error", "-y", "-framerate", "8", "-i", path.join(frames, "f%04d.png"), "-vf",
    "scale=400:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=160:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle",
    path.join(DOCS, "demo.gif")], { stdio: "inherit" });
  console.log(enc.status === 0 ? "ok demo.gif" : "ffmpeg falhou");
}

if (MODE === "all" || MODE === "cover") {
  await viewport(1280, 640, 2);
  fs.copyFileSync(path.join(TOOLS, "cover.html"), path.join(WORK, "cover.html"));
  const l = once("Page.loadEventFired");
  await send("Page.navigate", { url: "file://" + path.join(WORK, "cover.html") });
  await l;
  await sleep(800);
  await shot(path.join(DOCS, "cover.png"));
}

ws.close();
chrome.kill();
process.exit(0);
