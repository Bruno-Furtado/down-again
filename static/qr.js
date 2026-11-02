"use strict";
// Gerador de QR code mínimo e sem dependências (o painel precisa funcionar sem internet).
// Modo byte, correção nível M, versões 1 a 6 (até 106 bytes: sobra para "http://<nome>.local:porta").
// Segue o algoritmo de referência do Project Nayuki (QR Code generator library, MIT).
const QR = (() => {
  // nível M: [palavras de dados, palavras de correção por bloco, blocos]
  const SPEC = [null, [16, 10, 1], [28, 16, 1], [44, 26, 1], [64, 18, 2], [86, 24, 2], [108, 16, 4]];

  // Reed-Solomon em GF(256), polinômio 0x11D
  function mul(x, y) {
    let z = 0;
    for (let i = 7; i >= 0; i--) {
      z = (z << 1) ^ ((z >>> 7) * 0x11d);
      z ^= ((y >>> i) & 1) * x;
    }
    return z;
  }
  function rsDivisor(degree) {
    const r = new Array(degree).fill(0);
    r[degree - 1] = 1;
    let root = 1;
    for (let i = 0; i < degree; i++) {
      for (let j = 0; j < r.length; j++) {
        r[j] = mul(r[j], root);
        if (j + 1 < r.length) r[j] ^= r[j + 1];
      }
      root = mul(root, 0x02);
    }
    return r;
  }
  function rsRemainder(data, div) {
    const r = div.map(() => 0);
    for (const b of data) {
      const f = b ^ r.shift();
      r.push(0);
      div.forEach((c, i) => { r[i] ^= mul(c, f); });
    }
    return r;
  }

  function encode(text) {
    const bytes = Array.from(new TextEncoder().encode(text));
    let ver = 1;
    while (ver <= 6 && 4 + 8 + bytes.length * 8 > SPEC[ver][0] * 8) ver++;
    if (ver > 6) return null;
    const [dataLen, ecLen, blocks] = SPEC[ver];
    const bits = [];
    const push = (val, n) => { for (let i = n - 1; i >= 0; i--) bits.push((val >>> i) & 1); };
    push(4, 4);                       // modo byte
    push(bytes.length, 8);
    bytes.forEach((b) => push(b, 8));
    const cap = dataLen * 8;
    push(0, Math.min(4, cap - bits.length));
    push(0, (8 - (bits.length % 8)) % 8);
    for (let pad = 0xec; bits.length < cap; pad ^= 0xec ^ 0x11) push(pad, 8);
    const data = [];
    for (let i = 0; i < bits.length; i += 8) data.push(bits.slice(i, i + 8).reduce((a, b) => (a << 1) | b, 0));
    // nas versões 1 a 6 do nível M todos os blocos têm o mesmo tamanho
    const per = dataLen / blocks, div = rsDivisor(ecLen), dataBlocks = [], ecBlocks = [];
    for (let b = 0; b < blocks; b++) {
      const d = data.slice(b * per, (b + 1) * per);
      dataBlocks.push(d);
      ecBlocks.push(rsRemainder(d, div));
    }
    const codewords = [];
    for (let i = 0; i < per; i++) dataBlocks.forEach((d) => codewords.push(d[i]));
    for (let i = 0; i < ecLen; i++) ecBlocks.forEach((e) => codewords.push(e[i]));
    return { ver, codewords };
  }

  function drawFormat(set, size, mask) {
    const data = mask;                // nível M = 00
    let rem = data;
    for (let i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
    const bits = ((data << 10) | rem) ^ 0x5412;
    const bit = (i) => ((bits >>> i) & 1) === 1;
    for (let i = 0; i <= 5; i++) set(8, i, bit(i));
    set(8, 7, bit(6));
    set(8, 8, bit(7));
    set(7, 8, bit(8));
    for (let i = 9; i < 15; i++) set(14 - i, 8, bit(i));
    for (let i = 0; i < 8; i++) set(size - 1 - i, 8, bit(i));
    for (let i = 8; i < 15; i++) set(8, size - 15 + i, bit(i));
    set(8, size - 8, true);           // módulo escuro fixo
  }

  const MASKS = [
    (x, y) => (x + y) % 2 === 0, (x, y) => y % 2 === 0, (x) => x % 3 === 0, (x, y) => (x + y) % 3 === 0,
    (x, y) => (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0, (x, y) => ((x * y) % 2) + ((x * y) % 3) === 0,
    (x, y) => (((x * y) % 2) + ((x * y) % 3)) % 2 === 0, (x, y) => (((x + y) % 2) + ((x * y) % 3)) % 2 === 0,
  ];

  function penalty(t, size) {
    let p = 0, dark = 0;
    const at = (a, i, j) => (a ? t[j][i] : t[i][j]);
    for (let a = 0; a < 2; a++) {
      for (let i = 0; i < size; i++) {
        let run = 1;
        for (let j = 1; j < size; j++) {
          if (at(a, i, j) === at(a, i, j - 1)) { run++; if (run === 5) p += 3; else if (run > 5) p++; } else run = 1;
        }
        for (let j = 0; j + 7 <= size; j++) {     // parecido com o padrão localizador
          if (at(a, i, j) && !at(a, i, j + 1) && at(a, i, j + 2) && at(a, i, j + 3) && at(a, i, j + 4) && !at(a, i, j + 5) && at(a, i, j + 6)) p += 40;
        }
      }
    }
    for (let y = 0; y < size - 1; y++) {
      for (let x = 0; x < size - 1; x++) {
        const c = t[y][x];
        if (c === t[y][x + 1] && c === t[y + 1][x] && c === t[y + 1][x + 1]) p += 3;
      }
    }
    t.forEach((r) => r.forEach((c) => { if (c) dark++; }));
    return p + Math.floor(Math.abs(dark * 20 - size * size * 10) / (size * size)) * 10;
  }

  function matrix(text) {
    const enc = encode(text);
    if (!enc) return null;
    const size = enc.ver * 4 + 17;
    const mod = [...Array(size)].map(() => Array(size).fill(false));
    const fn = [...Array(size)].map(() => Array(size).fill(false));
    const set = (x, y, dark) => { mod[y][x] = dark; fn[y][x] = true; };
    for (let i = 0; i < size; i++) { set(6, i, i % 2 === 0); set(i, 6, i % 2 === 0); }
    for (const [cx, cy] of [[3, 3], [size - 4, 3], [3, size - 4]]) {
      for (let dy = -4; dy <= 4; dy++) {
        for (let dx = -4; dx <= 4; dx++) {
          const x = cx + dx, y = cy + dy, d = Math.max(Math.abs(dx), Math.abs(dy));
          if (x >= 0 && x < size && y >= 0 && y < size) set(x, y, d !== 2 && d !== 4);
        }
      }
    }
    if (enc.ver > 1) {                // versões 2 a 6 têm um único padrão de alinhamento
      const c = size - 7;
      for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) set(c + dx, c + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
    }
    drawFormat(set, size, 0);         // reserva a área do formato
    let i = 0;
    const total = enc.codewords.length * 8;
    for (let right = size - 1; right >= 1; right -= 2) {
      if (right === 6) right = 5;
      for (let v = 0; v < size; v++) {
        for (let j = 0; j < 2; j++) {
          const x = right - j, up = ((right + 1) & 2) === 0, y = up ? size - 1 - v : v;
          if (!fn[y][x] && i < total) {
            mod[y][x] = ((enc.codewords[i >>> 3] >>> (7 - (i & 7))) & 1) === 1;
            i++;
          }
        }
      }
    }
    let best = null;
    for (let m = 0; m < 8; m++) {
      const t = mod.map((r) => r.slice());
      for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) if (!fn[y][x] && MASKS[m](x, y)) t[y][x] = !t[y][x];
      drawFormat((x, y, d) => { t[y][x] = d; }, size, m);
      const p = penalty(t, size);
      if (!best || p < best.p) best = { p, t };
    }
    return best.t;
  }

  // SVG com margem de 4 módulos (zona de silêncio exigida pela especificação)
  function svg(text) {
    const m = matrix(text);
    if (!m) return null;
    const q = 4, n = m.length + q * 2;
    let d = "";
    m.forEach((row, y) => row.forEach((c, x) => { if (c) d += `M${x + q} ${y + q}h1v1h-1z`; }));
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${n} ${n}" shape-rendering="crispEdges" role="img"><rect width="${n}" height="${n}" fill="#fff"/><path d="${d}" fill="#000"/></svg>`;
  }

  return { svg, matrix };
})();
