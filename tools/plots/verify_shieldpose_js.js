// Verifies tools/plots/shieldpose.js against the C# solver's output.
//
// For every character in data/shieldpose_web.json, re-computes every row of data/<code>.csv (grid +
// polar, including the angle-360 rows) and every Nth sample of data/<code>_hurtboxes.csv, and reports the
// max abs error and the fraction of bit-identical float32 values. Grid rows also check settle(): the
// integer stick (stick_x, stick_y) must settle to the row's (angle, mag).
//
// Usage (repo root):  node tools/plots/verify_shieldpose_js.js [--hurt-stride N] [--char Fx Ms] [--tol 1e-5]
//   --hurt-stride 1 (default) checks every hurtbox sample; 0 skips hurtboxes.
// Exit code 1 if any character exceeds the tolerance.
'use strict';
const fs = require('fs');
const path = require('path');
const ShieldPose = require('./shieldpose.js');

const ROOT = path.resolve(__dirname, '..', '..');
const DATA = path.join(ROOT, 'data');
const args = process.argv.slice(2);
let stride = 1, tol = 1e-5, only = null;
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--hurt-stride') stride = +args[++i];
  else if (args[i] === '--tol') tol = +args[++i];
  else if (args[i] === '--char') { only = []; while (i + 1 < args.length && !args[i + 1].startsWith('--')) only.push(args[++i]); }
}

const SP = ShieldPose.load(fs.readFileSync(path.join(DATA, 'shieldpose_web.json'), 'utf8'));
const fr = Math.fround;
const codes = only || SP.codes;
let fail = false;
console.log('code  rows  bone_err    radius_err  bone_ident  settle_bad  hb_samples hb_err     hb_ident');
for (const code of codes) {
  const lines = fs.readFileSync(path.join(DATA, `${code}.csv`), 'utf8').split(/\r?\n/).filter(Boolean);
  const hdr = lines[0].split(',');
  const ix = n => hdr.indexOf(n);
  let hb = null;
  const hbPath = path.join(DATA, `${code}_hurtboxes.csv`);
  if (stride > 0 && fs.existsSync(hbPath)) {
    hb = new Map();
    const hl = fs.readFileSync(hbPath, 'utf8').split(/\r?\n/);
    for (let i = 1; i < hl.length; i++) {
      if (!hl[i]) continue;
      const p = hl[i].split(',');
      const key = p.slice(0, 5).join(',');
      let arr = hb.get(key); if (!arr) hb.set(key, arr = []);
      arr.push(p);
    }
  }
  let boneErr = 0, radErr = 0, ident = 0, total = 0, settleBad = 0, hbErr = 0, hbIdent = 0, hbTotal = 0, hbSamples = 0;
  let worst = '';
  const fm = SP.chars[code];
  for (let i = 1; i < lines.length; i++) {
    const p = lines[i].split(',');
    const sweep = p[ix('sweep')], angle = +p[ix('angle')], mag = fr(+p[ix('mag')]);
    const wantHb = hb && ((i - 1) % stride === 0);
    const r = SP.pose(code, angle, mag, { hurtboxes: !!wantHb });
    const exp = ['bone_x', 'bone_y', 'bone_z'].map(n => fr(+p[ix(n)]));
    for (let k = 0; k < 3; k++) {
      const d = Math.abs(r.centre[k] - exp[k]);
      if (d > boneErr) { boneErr = d; worst = `row ${i} ${lines[i]} js ${r.centre}`; }
      if (d === 0) ident++;
      total++;
    }
    radErr = Math.max(radErr, Math.abs(r.radiusFull - fr(+p[ix('shield_radius_full')])),
      Math.abs(r.radiusMin - fr(+p[ix('shield_radius_min')])));
    if (sweep === 'grid') {
      const kx = +p[ix('stick_x')], ky = +p[ix('stick_y')];
      const s = SP.settle(kx, ky, angle === 360 ? 'below' : 'fresh');
      const expAngle = fm.hasTilt ? fr(angle) : fr(angle);
      if (s.kx !== kx || s.ky !== ky || s.mag !== mag || (fm.hasTilt ? s.angle !== expAngle : (s.angle !== expAngle && !(s.zeroAngle && expAngle === 0))))
        settleBad++;
    }
    if (wantHb) {
      const key = p.slice(0, 5).join(',');
      const rows = hb.get(key) || [];
      if (rows.length !== fm.hurtboxes.length) throw new Error(`${code}: hurtbox rows for ${key}: ${rows.length}`);
      hbSamples++;
      for (const q of rows) {
        const h = +q[5], got = r.hurtboxes[h];
        if (q[10] === '') { if (got !== null) settleBad++; continue; }
        for (let k = 0; k < 7; k++) {
          const e = fr(+q[10 + k]);
          const d = Math.abs(got[k] - e);
          hbErr = Math.max(hbErr, d);
          if (d === 0) hbIdent++;
          hbTotal++;
        }
      }
    }
  }
  const bad = boneErr > tol || radErr > tol || hbErr > tol || settleBad > 0;
  if (bad) fail = true;
  console.log(`${code.padEnd(4)} ${String(lines.length - 1).padStart(5)}  ${boneErr.toExponential(2).padEnd(10)}  ${radErr.toExponential(2).padEnd(10)}  ` +
    `${(100 * ident / total).toFixed(3).padStart(7)}%  ${String(settleBad).padStart(10)}  ${String(hbSamples).padStart(10)} ${hbErr.toExponential(2).padEnd(10)} ` +
    `${hbTotal ? (100 * hbIdent / hbTotal).toFixed(3).padStart(7) + '%' : '-'}${bad ? '  FAIL' : ''}`);
  if (bad && worst) console.log('   worst bone:', worst);
}
console.log(fail ? 'FAIL' : `PASS (tolerance ${tol})`);
process.exit(fail ? 1 : 0);
