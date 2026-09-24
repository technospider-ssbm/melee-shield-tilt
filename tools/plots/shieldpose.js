/* shieldpose.js: a JavaScript port of tools/ShieldPose (the C# solver) for the web explorer.
 *
 * Input: the JSON written by `ShieldPose --export-web` (skeleton subset, ShieldPose SRT, raw Guard
 * FObj tracks, hurtboxes, PlCo constants). Output: the settled shield pose for a stick state, exactly as
 * FighterModel.LivePose / World / Sweep.Eval compute it (docs/MECHANICS.md).
 *
 * float32: every value the C# holds in a `float` goes through Math.fround after each operation, in the
 * same order. PSMTXConcat's fused multiply-adds are emulated with a correctly rounded fmaf. Doubles are
 * used exactly where the C# uses them (1.0/fterm, 1.0/scale in MtxSRT, PI/2*facing, pi - atanf in
 * lb_8000D008, the radius chain scale cbrt(|det|)). The one unavoidable difference: sinf/cosf/atanf/acosf
 * are Math.fround(Math.sin(x)) etc. (correctly rounded double libm, then rounded to float) where .NET uses
 * the C runtime's float routines; the two can differ in the last float ulp.
 *
 * API
 *   const SP = ShieldPose.load(exportJson);         // parsed object or JSON string
 *   SP.codes                                         // character codes in the export
 *   SP.settle(kx, ky, approach, {ucf})  -> {kx, ky, lx, ly, angle, mag, zeroAngle, ucf}
 *       opts.ucf: apply UCF 0.84 1.0 cardinals (see ucfCardinal); off = vanilla. `target` = raw stick angle.
 *   SP.easeGuard(x8, targetDeg) -> settled x8 after holding the stick (history-dependent 10 vs 370 at 0 deg).
 *       kx, ky: raw integer stick units (s8 range, e.g. -80..80); applies HSD_PadClampCheck3 (radius 80,
 *       float->s8 truncation), /80, the per-axis 0.28 deadzone, then ftCo_80091BC4's settled angle/weight.
 *       approach: 'below' (or 360 / true) selects the frame-370 rest state for a stick at exactly 0 deg
 *       with m > 0 (MECHANICS 1.2); anything else gives the frame-10 state.
 *   SP.pose(code, angle, mag, opts) -> {centre:[x,y,z], radiusScale, bFull, radiusFull, radiusMin,
 *                                       hurtboxes:[[x1,y1,z1,x2,y2,z2,r],...]}
 *       angle: settled eased angle g in [0, 360] (Guard frame = 10 + g); mag: blend weight x4 in [0, 1].
 *       radiusScale = cbrt(|det|) of the shield bone's parent world matrix (world radius = b * radiusScale).
 *       opts.hurtboxes = false skips hurtbox posing (faster, for paths).
 *   SP.bubbleScale(code, health, lightshield) -> b (inlineB0, ftCo_Guard.c:177-191, f32)
 */
(function (root) {
  'use strict';
  const fr = Math.fround;

  // ------------------------------------------------------------------ float helpers

  /** Correctly rounded float32 fused multiply-add a*b + c (inputs are float32 values). */
  function fmaf(a, b, c) {
    const p = a * b;                 // exact in double (24 x 24 bits)
    const s = p + c;
    const f = fr(s);
    const bb = s - p;                // TwoSum error term of p + c
    const e = (p - (s - bb)) + (c - bb);
    if (e === 0 || f === s) return f;
    const m = 2 * s - f;             // the other float neighbour, if s is exactly their midpoint
    if (m !== f && fr(m) === m) return (e > 0) === (m > f) ? m : f;
    return f;
  }
  const sinf = x => fr(Math.sin(x));
  const cosf = x => fr(Math.cos(x));
  const atanf = x => fr(Math.atan(x));
  const acosf = x => fr(Math.acos(x));
  const sqrtf = x => fr(Math.sqrt(x));

  const F_1EM4 = fr(1e-4), F_1EM3 = fr(1e-3), F_1EM5 = fr(0.00001), F_1EM10 = fr(1.000000013351432e-10);
  const F_RAD2DEG = fr(57.29577951), F_PI = fr(Math.PI);

  // ------------------------------------------------------------------ FObj interpreter (FObj.cs)

  const OP_CON = 1, OP_LIN = 2, OP_SPL0 = 3, OP_SPL = 4, OP_SLP = 5, OP_KEY = 6;

  function hermite(fterm, time, p0, p1, d0, d1) {
    const _1_T2 = fr(time * time);
    const t2 = fr(fterm * fterm);
    const t2_T = fr(_1_T2 * fterm);
    const t3_T2 = fr(t2 * fr(_1_T2 * time));
    const _2t3_T3 = fr(fr(2 * t3_T2) * fterm);
    const _3t2_T2 = fr(fr(3 * _1_T2) * t2);
    const a = fr(d1 * fr(t3_T2 - t2_T));
    const b = fr(d0 * fr(time + fr(fr(t3_T2 - t2_T) - t2_T)));
    const c = fr(p0 * fr(1 + fr(_2t3_T3 - _3t2_T2)));
    const d = fr(p1 * fr(-_2t3_T3 + _3t2_T2));
    return fr(a + fr(b + fr(c + d)));
  }

  function parseFloatF(f, frac) {
    const d = f.D.data;
    if (frac === 0) {
      const v = f.D.view.getFloat32(f.Ad, true);
      f.Ad += 4;
      return v;
    }
    const denom = 1 << (frac & 0x1F);
    let numer;
    switch (frac & 0xE0) {
      case 0x60: numer = (d[f.Ad] << 24) >> 24; f.Ad += 1; break;
      case 0x80: numer = d[f.Ad]; f.Ad += 1; break;
      case 0x20: numer = (((d[f.Ad + 1] << 8) | d[f.Ad]) << 16) >> 16; f.Ad += 2; break;
      case 0x40: numer = (d[f.Ad + 1] << 8) | d[f.Ad]; f.Ad += 2; break;
      default: return 0;
    }
    return fr(numer / denom);
  }

  function parsePackInfo(f) {
    const d = f.D.data;
    let b = d[f.Ad++];
    let nb = ((b >> 4) & 7) + 1;
    let shift = 3;
    if ((b & 0x80) === 0) return nb;
    do {
      b = d[f.Ad++];
      nb += (b & 0x7F) << shift;
      shift += 7;
    } while ((b & 0x80) !== 0);
    return nb >>> 0;
  }

  function parseWait(f) {
    const d = f.D.data;
    let wait = 0, shift = 0, b;
    do {
      b = d[f.Ad++];
      wait |= (b & 0x7F) << shift;
      shift += 7;
    } while ((b & 0x80) !== 0);
    return wait;
  }

  const getState = f => f.Flags & 0xF;
  function setState(f, s) { f.Flags = ((s & 0xF) | (f.Flags & 0xF0)) & 0xFF; return s; }

  function launchKeyData(f) {
    if ((f.Flags & 0x40) !== 0) {
      f.OpIntrp = f.Op;
      f.Flags &= ~0x40 & 0xFF;
      f.Flags |= 0x80;
      f.P0 = f.P1;
    }
  }

  function loadWait(f) {
    if (f.Ad >= f.D.length) return 6;
    f.Fterm = parseWait(f) & 0xFFFF;
    f.Flags |= 0x20;
    return setState(f, 2);
  }

  function loadData(f) {
    if (f.Ad >= f.D.length) return 6;
    f.OpIntrp = f.Op;
    if (f.NbPack === 0) {
      f.Op = f.D.data[f.Ad] & 0xF;
      f.NbPack = parsePackInfo(f) & 0xFFFF;
    }
    f.NbPack = (f.NbPack - 1) & 0xFFFF;
    const next = getState(f) === 1 ? 3 : 4;
    switch (f.Op) {
      case OP_CON:
      case OP_LIN:
        f.P0 = f.P1;
        f.P1 = parseFloatF(f, f.D.fracValue);
        if (f.OpIntrp !== OP_SLP) { f.D0 = f.D1; f.D1 = 0; }
        return setState(f, next);
      case OP_SPL0:
        f.P0 = f.P1;
        f.D0 = f.D1;
        f.P1 = parseFloatF(f, f.D.fracValue);
        f.D1 = 0;
        return setState(f, next);
      case OP_SPL:
        f.P0 = f.P1;
        f.P1 = parseFloatF(f, f.D.fracValue);
        f.D0 = f.D1;
        f.D1 = parseFloatF(f, f.D.fracSlope);
        return setState(f, next);
      case OP_SLP:
        f.D0 = f.D1;
        f.D1 = parseFloatF(f, f.D.fracSlope);
        return getState(f);
      case OP_KEY:
        launchKeyData(f);
        f.P1 = parseFloatF(f, f.D.fracValue);
        f.Flags |= 0x40;
        return setState(f, next);
      default:
        return 0;
    }
  }

  function updateAnim(f) {
    let v;
    switch (f.OpIntrp) {
      case OP_KEY:
        if ((f.Flags & 0x80) !== 0) { v = f.P0; f.Flags &= 0x7F; }
        else return;
        break;
      case OP_CON:
        v = f.Time >= f.Fterm ? f.P1 : f.P0;
        break;
      case OP_LIN:
        if ((f.Flags & 0x20) !== 0) {
          f.Flags &= 0xDF;
          if (f.Fterm !== 0) f.D0 = fr(fr(f.P1 - f.P0) / f.Fterm);
          else { f.D0 = 0; f.P0 = f.P1; }
        }
        v = fr(fr(f.D0 * f.Time) + f.P0);
        break;
      case OP_SPL0:
      case OP_SPL:
      case OP_SLP:
        if (f.Fterm !== 0) v = hermite(fr(1.0 / f.Fterm), f.Time, f.P0, f.P1, f.D0, f.D1);
        else v = f.P1;
        break;
      default:
        return;
    }
    f.out = v;
  }

  function interpret(f, rate) {
    let fterm = 0;
    let state = getState(f);
    if (state === 0) return;
    f.Time = fr(f.Time + rate);
    if (f.Time < 0) return;
    for (;;) {
      switch (state) {
        case 6:
          f.Time = fr(f.Time + fterm);
          launchKeyData(f);
          updateAnim(f);
          return;
        case 1:
        case 2:
          state = loadData(f);
          break;
        case 3:
          if ((f.Flags & 0x80) !== 0) updateAnim(f);
          state = loadWait(f);
          break;
        case 4:
          if (f.Fterm <= f.Time) {
            state = 3;
            fterm = f.Fterm;
            f.Time = fr(f.Time - f.Fterm);
            setState(f, state);
            break;
          }
          updateAnim(f);
          setState(f, 5);
          return;
        case 5:
          state = 4;
          setState(f, state);
          break;
        default:
          return;
      }
    }
  }

  /** FObjInterp.Evaluate: value written to the joint for `frame`, or null. */
  function evalTrack(d, frame, endFrame) {
    const f = { D: d, Ad: 0, Flags: 0, Op: 0, OpIntrp: 0, NbPack: 0, Fterm: 0,
      Time: fr(d.startFrame + frame), P0: 0, P1: 0, D0: 0, D1: 0, out: null };
    setState(f, 1);
    interpret(f, 0);
    if (endFrame <= frame) {
      if (f.OpIntrp === OP_KEY) interpret(f, 1);
      setState(f, 0);
    }
    return f.out;
  }

  // ------------------------------------------------------------------ quaternion / matrix math (F32Math.cs)

  function eulerToQuat(ex, ey, ez) {
    const cx = cosf(fr(0.5 * ex)), cy = cosf(fr(0.5 * ey)), cz = cosf(fr(0.5 * ez));
    const sx = sinf(fr(0.5 * ex)), sy = sinf(fr(0.5 * ey)), sz = sinf(fr(0.5 * ez));
    const ss = fr(sy * sz), cc = fr(cy * cz);
    return [
      fr(fr(sx * cc) - fr(cx * ss)),
      fr(fr(cz * fr(cx * sy)) + fr(sz * fr(sx * cy))),
      fr(fr(sz * fr(cx * cy)) - fr(cz * fr(sx * sy))),
      fr(fr(cx * cc) + fr(sx * ss)),
    ]; // x, y, z, w
  }

  function slerp(p, q, t) {
    const cosom = fr(fr(fr(fr(p[0] * q[0]) + fr(p[1] * q[1])) + fr(p[2] * q[2])) + fr(p[3] * q[3]));
    let sp, sq;
    if (fr(1 + cosom) > F_1EM10) {
      if (fr(1 - cosom) > F_1EM10) {
        const theta = acosf(cosom);
        const sinom = sinf(theta);
        sp = fr(sinf(fr(fr(1 - t) * theta)) / sinom);
        sq = fr(sinf(fr(t * theta)) / sinom);
      } else {
        sq = t;
        sp = fr(1.0 - t);
      }
    } else if (t < 0.5) {
      sp = sinf(fr(Math.PI / 2 * fr(1 - fr(2 * t))));
      sq = sinf(fr(Math.PI / 2 * fr(2 * t)));
    } else {
      t = fr(t - 0.5);
      const t2 = fr(2 * t);
      sp = sinf(fr(Math.PI / 2 * fr(1 - t2)));
      sq = sinf(fr(Math.PI / 2 * t2));
    }
    return [0, 1, 2, 3].map(i => fr(fr(sp * p[i]) + fr(sq * q[i])));
  }

  // Matrices: Float64Array(12) holding float32 values, row-major 3x4 (m[r*4+c]).
  function mtxSRT(s, r, t, pscl) {
    const sinX = sinf(r[0]), cosX = cosf(r[0]);
    const sinY = sinf(r[1]), cosY = cosf(r[1]);
    const sinZ = sinf(r[2]), cosZ = cosf(r[2]);
    let x2 = s[0], x1 = s[0], x0 = s[0];
    let y2 = s[1], y1 = s[1], y0 = s[1];
    let z2 = s[2], z1 = s[2], z0 = s[2];
    if (pscl) {
      const t1 = fr(1.0 / pscl[0]), t2 = fr(1.0 / pscl[1]), t3 = fr(1.0 / pscl[2]);
      y2 = fr(y2 * fr(pscl[1] * t1));
      z2 = fr(z2 * fr(pscl[2] * t1));
      x1 = fr(x1 * fr(pscl[0] * t2));
      z1 = fr(z1 * fr(pscl[2] * t2));
      x0 = fr(x0 * fr(pscl[0] * t3));
      y0 = fr(y0 * fr(pscl[1] * t3));
    }
    const m = new Float64Array(12);
    m[0] = fr(cosZ * fr(x2 * cosY));
    m[4] = fr(sinZ * fr(x1 * cosY));
    m[8] = fr(-x0 * sinY);
    m[1] = fr(y2 * fr(fr(cosZ * fr(sinX * sinY)) - fr(cosX * sinZ)));
    m[5] = fr(y1 * fr(fr(sinZ * fr(sinX * sinY)) + fr(cosX * cosZ)));
    m[9] = fr(cosY * fr(y0 * sinX));
    m[2] = fr(z2 * fr(fr(cosZ * fr(cosX * sinY)) + fr(sinX * sinZ)));
    m[6] = fr(z1 * fr(fr(sinZ * fr(cosX * sinY)) - fr(sinX * cosZ)));
    m[10] = fr(cosY * fr(z0 * cosX));
    m[3] = t[0]; m[7] = t[1]; m[11] = t[2];
    return m;
  }

  function scaleMtx(x, y, z) { const m = new Float64Array(12); m[0] = x; m[5] = y; m[10] = z; return m; }
  function transMtx(x, y, z) { const m = new Float64Array(12); m[0] = 1; m[5] = 1; m[10] = 1; m[3] = x; m[7] = y; m[11] = z; return m; }

  function quatMtx(q) {
    const [x, y, z, w] = q;
    const s = fr(2 / fr(fr(w * w) + fr(fr(z * z) + fr(fr(x * x) + fr(y * y)))));
    const xs = fr(x * s), ys = fr(y * s), zs = fr(z * s);
    const wx = fr(w * xs), wy = fr(w * ys), wz = fr(w * zs);
    const xx = fr(x * xs), xy = fr(x * ys), xz = fr(x * zs);
    const yy = fr(y * ys), yz = fr(y * zs), zz = fr(z * zs);
    const m = new Float64Array(12);
    m[0] = fr(1 - fr(yy + zz)); m[1] = fr(xy - wz); m[2] = fr(xz + wy);
    m[4] = fr(xy + wz); m[5] = fr(1 - fr(xx + zz)); m[6] = fr(yz - wx);
    m[8] = fr(xz - wy); m[9] = fr(yz + wx); m[10] = fr(1 - fr(xx + yy));
    return m;
  }

  /** PSMTXConcat(a, b) = a*b with fused multiply-adds in paired-single order (F32.Concat). */
  function concat(a, b) {
    const o = new Float64Array(12);
    for (let i = 0; i < 3; i++) {
      const a0 = a[i * 4], a1 = a[i * 4 + 1], a2 = a[i * 4 + 2], a3 = a[i * 4 + 3];
      for (let j = 0; j < 4; j++) {
        let v = fr(b[j] * a0);
        v = fmaf(b[4 + j], a1, v);
        v = fmaf(b[8 + j], a2, v);
        if (j === 3) v = fmaf(1, a3, v);
        o[i * 4 + j] = v;
      }
    }
    return o;
  }

  function mtxSRTQuat(s, q, t, pscl) {
    let m = scaleMtx(s[0], s[1], s[2]);
    if (pscl) m = concat(scaleMtx(pscl[0], pscl[1], pscl[2]), m);
    m = concat(quatMtx(q), m);
    if (pscl) m = concat(scaleMtx(fr(1.0 / pscl[0]), fr(1.0 / pscl[1]), fr(1.0 / pscl[2])), m);
    return concat(transMtx(t[0], t[1], t[2]), m);
  }

  function multVec(m, v) {
    return [0, 1, 2].map(r => fr(fr(fr(fr(m[r * 4] * v[0]) + fr(m[r * 4 + 1] * v[1])) + fr(m[r * 4 + 2] * v[2])) + m[r * 4 + 3]));
  }

  /** Determinant of the 3x3 part in double (F32.Det3). */
  function det3(m) {
    const a = m[0], b = m[1], c = m[2], d = m[4], e = m[5], f = m[6], g = m[8], h = m[9], i = m[10];
    return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g);
  }

  /** lb_8000D008(y, x), lb/lb_00CE.c:106-151. */
  function lbAtan2(y, x) {
    if (x < F_1EM5 && x > -F_1EM5) {
      if (y < F_1EM5 && y > -F_1EM5) return 0;
      const s = y < 0 ? -1 : 1;
      return fr((Math.PI / 2) * s);
    }
    if (x > 0) return atanf(fr(y / x));
    let r = fr(y / x);
    if (r < 0) r = -r;
    const sg = y < 0 ? -1 : 1;
    return fr(sg * (Math.PI - atanf(r)));
  }

  // ------------------------------------------------------------------ model

  const ZERO3 = [0, 0, 0];
  function srt(a9) { return { R: [a9[0], a9[1], a9[2]], S: [a9[3], a9[4], a9[5]], T: [a9[6], a9[7], a9[8]], Q: null, quat: false }; }
  function cloneSrt(s) { return { R: s.R.slice(), S: s.S.slice(), T: s.T.slice(), Q: s.Q ? s.Q.slice() : null, quat: s.quat }; }

  function b64bytes(s) {
    if (typeof atob === 'function') {
      const bin = atob(s); const u = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
      return u;
    }
    return new Uint8Array(Buffer.from(s, 'base64'));
  }

  function prepChar(code, c) {
    const f3 = a => a.map(fr);
    const joints = c.joints.map(([parent, flags, rest, sp, tracks]) => ({
      parent, classical: (flags & 1) !== 0, itemHold: (flags & 2) !== 0, dyn: (flags & 4) !== 0, b4: (flags & 8) !== 0,
      rest: srt(f3(rest)), sp: srt(f3(sp)),
      tracks: tracks.map(([type, startFrame, fracValue, fracSlope, length, b64]) => {
        const data = b64bytes(b64);
        return { type, startFrame, fracValue, fracSlope, length, data,
          view: new DataView(data.buffer, data.byteOffset, data.byteLength) };
      }),
    }));
    return {
      code, name: c.name, kind: c.kind, hasTilt: c.has_tilt, endFrame: fr(c.end_frame),
      modelScale: fr(c.model_scale), shieldSize: fr(c.shield_size), shieldJoint: c.shield_joint, joints,
      hurtboxes: c.hurtboxes.map(h => ({ joint: h[0], part: h[1], type: h[2], grab: h[3],
        A: f3(h.slice(4, 7)), B: f3(h.slice(7, 10)), R: fr(h[10]) })),
      animCache: new Map(), raw: c,
    };
  }

  function load(json) {
    const ex = typeof json === 'string' ? JSON.parse(json) : json;
    const cm = ex.common;
    const C = { dzx: fr(cm.deadzone_x), dzy: fr(cm.deadzone_y), x260: fr(cm.x260), x264: fr(cm.x264),
      x2D4: fr(cm.x2D4), x2D8: fr(cm.x2D8) };
    const chars = {};
    for (const code of Object.keys(ex.chars)) chars[code] = prepChar(code, ex.chars[code]);

    /** FighterModel.BubbleScale (inlineB0, ftCo_Guard.c:177-191). */
    function bubbleScale(code, health, ls) {
      const fm = chars[code];
      health = fr(health); ls = fr(ls);
      if (fm.kind === 14) return fm.shieldSize;
      const n1 = fr(fr(health / C.x260) * fr(fr(ls * fr(C.x2D8 - C.x2D4)) + C.x2D4));
      const n2 = fr(1 - C.x264);
      const n3 = fr(fr(n2 * n1) + C.x264);
      return fr(n3 * fm.shieldSize);
    }

    function animPose(fm, frame) {
      const hit = fm.animCache.get(frame);
      if (hit) return hit;
      const invMs = fr(1.0 / fm.modelScale);
      const a = fm.joints.map((ji, j) => {
        const s = cloneSrt(ji.rest);
        if (j >= 1 && ji.itemHold) s.S = [invMs, invMs, invMs];
        s.quat = false;
        if (j === 0 || !ji.dyn) {
          for (const tr of ji.tracks) {
            const v = evalTrack(tr, frame, fm.endFrame);
            if (v === null) continue;
            const sc = Math.abs(v) < F_1EM3 ? F_1EM3 : v;
            switch (tr.type) {
              case 1: s.R[0] = v; break;
              case 2: s.R[1] = v; break;
              case 3: s.R[2] = v; break;
              case 5: s.T[0] = v; break;
              case 6: s.T[1] = v; break;
              case 7: s.T[2] = v; break;
              case 8: s.S[0] = sc; break;
              case 9: s.S[1] = sc; break;
              case 10: s.S[2] = sc; break;
            }
          }
        }
        return s;
      });
      if (fm.animCache.size > 2048) fm.animCache.clear();
      fm.animCache.set(frame, a);
      return a;
    }

    /** lb_8000C868(SP, J2, J2, t = 1-w, t_inv = w). */
    function blendJointToward(sp, j2, t, tinv) {
      const o = cloneSrt(j2);
      for (let k = 0; k < 3; k++) {
        o.T[k] = fr(fr(sp.T[k] * t) + fr(j2.T[k] * tinv));
        o.S[k] = fr(fr(sp.S[k] * t) + fr(j2.S[k] * tinv));
      }
      if (!j2.quat) {
        const dx = fr(sp.R[0] - j2.R[0]), dy = fr(sp.R[1] - j2.R[1]), dz = fr(sp.R[2] - j2.R[2]);
        if (Math.abs(dx) <= F_1EM4 && Math.abs(dy) <= F_1EM4 && Math.abs(dz) <= F_1EM4) {
          o.R = sp.R.slice(); o.quat = false; return o;
        }
      }
      const qa = eulerToQuat(sp.R[0], sp.R[1], sp.R[2]);
      let qb = j2.quat ? j2.Q : eulerToQuat(j2.R[0], j2.R[1], j2.R[2]);
      const sq = i => fr(fr(qa[i] + qb[i]) * fr(qa[i] + qb[i]));
      const dq = i => fr(fr(qa[i] - qb[i]) * fr(qa[i] - qb[i]));
      const S = fr(fr(fr(sq(0) + sq(1)) + sq(2)) + sq(3));
      const D = fr(fr(fr(dq(0) + dq(1)) + dq(2)) + dq(3));
      if (D > S) qb = qb.map(v => -v);
      o.Q = slerp(qa, qb, tinv);
      o.quat = true;
      return o;
    }

    function applyRestWithItemHold(fm, live, useSp) {
      const invMs = fr(1.0 / fm.modelScale);
      for (let j = 1; j < fm.joints.length; j++) {
        const ji = fm.joints[j];
        const src = useSp ? ji.sp : ji.rest;
        if (ji.itemHold) {
          if (ji.dyn) live[j].T = src.T.slice();
          else { live[j].R = src.R.slice(); live[j].T = src.T.slice(); live[j].quat = false; }
          live[j].S = [invMs, invMs, invMs];
        } else if (ji.dyn) { live[j].S = src.S.slice(); live[j].T = src.T.slice(); }
        else { live[j] = cloneSrt(src); live[j].quat = false; }
      }
    }

    /** FighterModel.LivePose (ftCo_80091E78, ftCo_Guard.c:214-248). */
    function livePose(fm, frame, m) {
      const live = fm.joints.map(ji => cloneSrt(ji.rest));
      if (!fm.hasTilt) { applyRestWithItemHold(fm, live, false); return live; }
      if (m === 0) { applyRestWithItemHold(fm, live, true); return live; }
      const a = animPose(fm, frame);
      const t = fr(1 - m);
      for (let j = 1; j < fm.joints.length; j++) {
        const ji = fm.joints[j];
        if (ji.dyn) continue;
        let l = a[j];
        if (m < 1) {
          if (ji.b4) { l = cloneSrt(ji.sp); l.quat = false; }
          else l = blendJointToward(ji.sp, a[j], t, m);
        }
        live[j] = l;
      }
      return live;
    }

    /** FighterModel.World (HSD_JObjMakeMatrix) with TopN facing right. */
    function world(fm, live, facing, bubble) {
      live[0] = { R: [0, fr(Math.PI / 2 * facing), 0], S: [fm.modelScale, fm.modelScale, fm.modelScale], T: ZERO3.slice(), Q: null, quat: false };
      if (fm.shieldJoint >= 0) { live[fm.shieldJoint] = cloneSrt(live[fm.shieldJoint]); live[fm.shieldJoint].S = [bubble, bubble, bubble]; }
      const n = fm.joints.length, w = new Array(n), scl = new Array(n);
      for (let j = 0; j < n; j++) {
        const ji = fm.joints[j], s = live[j];
        const pscl = ji.parent >= 0 ? scl[ji.parent] : null;
        if (ji.classical) scl[j] = pscl;
        else scl[j] = pscl ? [fr(s.S[0] * pscl[0]), fr(s.S[1] * pscl[1]), fr(s.S[2] * pscl[2])] : s.S;
        const local = s.quat ? mtxSRTQuat(s.S, s.Q, s.T, pscl) : mtxSRT(s.S, s.R, s.T, pscl);
        w[j] = ji.parent >= 0 ? concat(w[ji.parent], local) : local;
      }
      return w;
    }

    /** Sweep.Eval + hurtbox rows. */
    function pose(code, angle, mag, opts) {
      const fm = chars[code];
      if (!fm) throw new Error('unknown character ' + code);
      const facing = (opts && opts.facing) || 1;
      const frame = fr(10 + fr(angle));
      mag = fr(mag);
      const bFull = bubbleScale(code, C.x260, 1);
      const bMin = bubbleScale(code, 0, 1);
      const w = world(fm, livePose(fm, frame, mag), facing, bFull);
      const sm = w[fm.shieldJoint], w0 = w[0];
      const par = fm.joints[fm.shieldJoint].parent;
      const chain = Math.cbrt(Math.abs(det3(w[par])));
      const res = {
        centre: [fr(sm[3] - w0[3]), fr(sm[7] - w0[7]), fr(sm[11] - w0[11])],
        radiusScale: chain, bFull, radiusFull: fr(bFull * chain), radiusMin: fr(bMin * chain),
        hurtboxes: null, world: opts && opts.world ? w : undefined,
      };
      if (!opts || opts.hurtboxes !== false) {
        res.hurtboxes = fm.hurtboxes.map(hb => {
          if (hb.joint < 0) return null;
          const m = w[hb.joint];
          const tcol = [m[3], m[7], m[11]];
          const isZero = v => v[0] === 0 && v[1] === 0 && v[2] === 0;
          const a = isZero(hb.A) ? tcol : multVec(m, hb.A);
          const b = isZero(hb.B) ? tcol : multVec(m, hb.B);
          const sc = Math.cbrt(Math.abs(det3(m)));
          return [a[0], a[1], a[2], b[0], b[1], b[2], fr(hb.R * sc)];
        });
      }
      return res;
    }

    // -------------------------------------------------------------- stick (Sweep.Clamp / StickGrid / Settled)

    /** HSD_PadClampCheck3(x, y, shift=1, min=0, max=80); inputs are s8. */
    function clamp(x, y) {
      const max = 80;
      let r = sqrtf(fr(fr(x * x) + fr(y * y)));
      if (r > max) {
        x = Math.trunc(fr(fr(x * max) / r));
        y = Math.trunc(fr(fr(y * max) / r));
      }
      return [x, y];
    }

    /** UCF 0.84 "1.0 cardinals" (Slippi `UCF Pad Buffer + 1.0 Cardinals.asm`, hook 8006B460): when one raw
     *  hardware axis is >= 80 from centre and the other is within +/-6, the fighter's stick is overwritten with
     *  exactly (+/-1.0, 0) or (0, +/-1.0). Vanilla truncation would give 0.9875 there. */
    function ucfCardinal(kx, ky) {
      if (Math.abs(kx) >= 80 && Math.abs(ky) <= 6) return [kx > 0 ? 80 : -80, 0];
      if (Math.abs(ky) >= 80 && Math.abs(kx) <= 6) return [0, ky > 0 ? 80 : -80];
      return null;
    }

    /** ftCo_80091BC4's angle update (ftCo_Guard.c:130-175), run each frame until it stops changing.
     *  x8 = Guard frame (10 + eased angle); targetDeg = stick angle in [0, 359] (0 for neutral too).
     *  Reproduces the hysteresis: easing to 0 from (180, 360) settles at x8 = 370, from [0, 180) at 10.
     *  x44C (easing rate) is 0.5 in PlCo.dat. */
    function easeGuard(x8, targetDeg) {
      const k = fr(0.5);
      targetDeg = fr(targetDeg);
      for (let i = 0; i < 600; i++) {
        const g = fr(x8 - 10);
        let d = fr(targetDeg - g);
        if (d > 180) d = fr(d - 360); else if (d < -180) d = fr(d + 360);
        const sm = fr(fr(d * k) + g);
        let ng;
        if (sm > 360) ng = fr(sm - 360);
        else { ng = sm; if (ng < 0) ng = fr(ng + 360); }
        const nx8 = fr(10 + ng);
        if (nx8 === x8) return x8;
        x8 = nx8;
      }
      return x8;
    }

    function settle(kx, ky, approach, opts) {
      kx = Math.max(-128, Math.min(127, Math.trunc(kx)));
      ky = Math.max(-128, Math.min(127, Math.trunc(ky)));
      const [x, y] = clamp(kx, ky);
      const nx = fr(x / 80), ny = fr(y / 80);
      let qx = Math.abs(nx) <= C.dzx ? 0 : x;
      let qy = Math.abs(ny) <= C.dzy ? 0 : y;
      const ucf = opts && opts.ucf ? ucfCardinal(kx, ky) : null;
      if (ucf) [qx, qy] = ucf;
      const lx = fr(qx / 80), ly = fr(qy / 80);
      let rad = lbAtan2(ly, lx);
      if (rad < 0) rad = fr(rad + fr(2 * F_PI));
      let deg = fr(rad * F_RAD2DEG);
      if (deg < 0) deg = 0;
      if (deg > 359) deg = 359;
      let mag = sqrtf(fr(fr(lx * lx) + fr(ly * ly)));
      if (mag > 1) mag = 1;
      const zeroAngle = deg === 0 && mag > 0;
      const below = approach === 'below' || approach === 360 || approach === true;
      return { kx: qx, ky: qy, lx, ly, angle: zeroAngle && below ? 360 : deg, target: deg, mag, zeroAngle, ucf: !!ucf };
    }

    return { codes: Object.keys(chars), chars, common: C, settle, easeGuard, pose, bubbleScale, clamp,
      _internal: { evalTrack, fmaf, lbAtan2, livePose, world } };
  }

  const api = { load };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.ShieldPose = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
