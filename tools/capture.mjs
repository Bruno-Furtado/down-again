// Regera as imagens de docs/ (capa, prints e GIF) a partir do painel de demonstração.
// Requer Google Chrome e ffmpeg. Sem dependências npm (usa o WebSocket nativo do Node 22+).
//
//   python3 tools/demo.py          # em outro terminal (porta 8766)
//   node tools/capture.mjs         # tudo; ou: node tools/capture.mjs shots|gif|cover|icons
//
// Gera docs/<idioma>/{cover.png, demo.gif, dashboard.png, report.png} para en, pt e zh.
// "icons" gera os ícones do app em static/ (não precisa da demo rodando).
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

const LANGS = (process.env.LANGS || "en,pt,zh").split(",");
const PREFS = { period: "7d", series: "24", installHidden: true };   // sem o aviso de instalar nas imagens
const IDENT = {
  en: { titular: "Jane Example", provedor: "Example ISP", endereco: "123 Example St, Springfield", plano: "500 Mbps fiber", cliente: "000123456", protocolos: "2026110100123, 2026110200456" },
  pt: { titular: "Maria Exemplo", provedor: "Operadora X", endereco: "Rua Exemplo, 123 — São Paulo/SP", plano: "500 Mbps fibra", cliente: "000123456", protocolos: "2026110100123, 2026110200456" },
  zh: { titular: "示例用户", provedor: "示例运营商", endereco: "示例路 123 号", plano: "500 Mbps 光纤", cliente: "000123456", protocolos: "2026110100123, 2026110200456" },
};

// Ícones do app (tela de início do celular e favicon): gradiente roxo com o pulso branco.
function iconSVG(size, rounded, scale) {
  const s = (size * scale) / 24, off = (size - 24 * s) / 2;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">` +
    `<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#5b6cf0"/><stop offset="1" stop-color="#8b5cf6"/></linearGradient></defs>` +
    `<rect width="${size}" height="${size}" rx="${rounded ? size * 0.225 : 0}" fill="url(#g)"/>` +
    `<path transform="translate(${off} ${off}) scale(${s})" d="M3 12h4l2.5-6 5 12 2.5-6h4" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
}
if (MODE === "icons") {
  const STATIC = path.join(TOOLS, "..", "static");
  fs.writeFileSync(path.join(STATIC, "icon.svg"), iconSVG(64, true, 0.62) + "\n");
  await send("Emulation.setDefaultBackgroundColorOverride", { color: { r: 0, g: 0, b: 0, a: 0 } });
  // iPhone arredonda sozinho e pinta transparência de preto: ícone quadrado e cheio.
  // "maskable" (Android): o desenho fica dentro da zona segura central.
  const SPECS = [["icon-180.png", 180, false, 0.6], ["icon-192.png", 192, true, 0.62], ["icon-512.png", 512, true, 0.62],
    ["icon-maskable-512.png", 512, false, 0.46]];
  for (const [name, size, rounded, scale] of SPECS) {
    await viewport(size, size, 1);
    const l = once("Page.loadEventFired");
    await send("Page.navigate", { url: "data:text/html," + encodeURIComponent(`<style>html,body{margin:0;background:transparent}svg{display:block}</style>${iconSVG(size, rounded, scale)}`) });
    await l;
    await sleep(200);
    await shot(path.join(STATIC, name));
  }
  ws.close();
  chrome.kill();
  process.exit(0);
}

for (const lang of LANGS) {
  const OUT = path.join(DOCS, lang);
  fs.mkdirSync(OUT, { recursive: true });
  const prefs = (extra) => Object.assign({ lang }, PREFS, extra);
  console.log("==", lang);

  if (MODE === "all" || MODE === "shots") {
    // painel no desktop, tema escuro
    await viewport(1280, 860, 2);
    await go(BASE + "/", prefs({ tema: "dark" }));
    await shot(path.join(OUT, "dashboard.png"));

    // celular claro e escuro (usados na capa)
    await viewport(390, 844, 3, true);
    for (const tema of ["light", "dark"]) {
      await go(BASE + "/", prefs({ tema }));
      await shot(path.join(WORK, `mobile-${lang}-${tema}.png`));
    }

    // relatório: só título e resumo (print curto)
    await viewport(1000, 1250, 2);
    await go(BASE + "/relatorio?from=2026-10-27&to=2026-11-02", { lang }, 2000);
    await js(`(() => { const v = ${JSON.stringify(IDENT[lang])}; document.querySelectorAll("#ident input").forEach((i) => { i.value = v[i.dataset.k] || ""; }); })()`);
    // print curto: esconde a identificação e corta logo depois do resumo
    await js(`document.querySelectorAll('[data-i18n="r.ident"], #ident, [data-i18n="r.editable"]').forEach((e) => { e.style.display = "none"; })`);
    const page = await rect(".page"), sum = await rect("#summary");
    await shot(path.join(OUT, "report.png"), { x: page.x, y: page.y, width: page.width, height: sum.y + sum.height - page.y + 28 });
  }

  if (MODE === "all" || MODE === "gif") {
    const frames = path.join(WORK, "frames");
    fs.rmSync(frames, { recursive: true, force: true });
    fs.mkdirSync(frames);
    let n = 0;
    const frame = async () => { const r = await send("Page.captureScreenshot", { format: "png" }); fs.writeFileSync(path.join(frames, `f${String(n++).padStart(4, "0")}.png`), Buffer.from(r.data, "base64")); };
    const hold = async (count, each) => { for (let i = 0; i < count; i++) { if (each) await js(each); await frame(); } };

    await viewport(390, 844, 2, true);
    await go(BASE + "/", prefs({ tema: "light" }), 3000);
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
    await hold(10, "__d.keep(1)");                 // online
    await js("__d.pending()");
    await hold(8, "__d.keep(1)");                  // instável
    await js("__d.down()");
    for (let i = 0; i < 26; i++) { await js("__d.tick(7)"); await frame(); }   // sem internet (avanço rápido)
    await js("__d.up()");
    await hold(12, "__d.keep(1)");                 // voltou
    const tl = await rect("#timeline");
    const target = tl.y - 90, ease = (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
    for (let i = 1; i <= 18; i++) { await js(`scrollTo(0, ${Math.round(target * ease(i / 18))})`); await frame(); }
    await hold(12);
    for (let i = 1; i <= 14; i++) { await js(`scrollTo(0, ${Math.round(target * (1 - ease(i / 14)))})`); await frame(); }
    await hold(3, "__d.keep(1)");
    await js(`document.querySelector("#theme").click()`);
    await hold(7, "__d.keep(1)");
    await js(`document.querySelector('#theme-menu [data-v="dark"]').click()`);
    await hold(14, "__d.keep(1)");
    const enc = spawnSync("ffmpeg", ["-v", "error", "-y", "-framerate", "8", "-i", path.join(frames, "f%04d.png"), "-vf",
      "scale=360:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle",
      path.join(OUT, "demo.gif")], { stdio: "inherit" });
    console.log(enc.status === 0 ? `ok demo.gif (${n} quadros)` : "ffmpeg falhou");
  }

  if (MODE === "all" || MODE === "cover") {
    for (const tema of ["light", "dark"]) fs.copyFileSync(path.join(WORK, `mobile-${lang}-${tema}.png`), path.join(WORK, `mobile-${tema}.png`));
    fs.copyFileSync(path.join(TOOLS, "cover.html"), path.join(WORK, "cover.html"));
    await viewport(1280, 640, 2);
    const l = once("Page.loadEventFired");
    await send("Page.navigate", { url: "file://" + path.join(WORK, "cover.html") + "?lang=" + lang });
    await l;
    await sleep(800);
    await shot(path.join(OUT, "cover.png"));
  }
}

ws.close();
chrome.kill();
process.exit(0);
