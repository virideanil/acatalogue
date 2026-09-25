// Step response of acatalogue's camera spring (semi-implicit Euler, c = 2*omega, dt = 1/120)
// versus the exact critically damped solution x(t) = (1 + w t) e^{-w t} (Holden's closed form).
const dt = 1 / 120;
function settle(omega, exactStep) {
  let x = 1, v = 0, t = 0; // target 0, start 1
  while (Math.abs(x) > 0.01 || Math.abs(v) > 0.01 * omega) {
    if (exactStep) { const y = omega, j0 = x, j1 = v + j0 * y, e = Math.exp(-y * dt); x = e * (j0 + j1 * dt); v = e * (v - j1 * y * dt); }
    else { v += (-omega * omega * x - 2 * omega * v) * dt; x += v * dt; }
    t += dt; if (t > 60) break;
  }
  return t;
}
for (const w of [9, 42]) {
  const te = settle(w, true), ts = settle(w, false);
  // exact continuous reference: solve (1 + w t) e^{-w t} = 0.01
  let tc = 0; while ((1 + w * tc) * Math.exp(-w * tc) > 0.01) tc += 1e-5;
  console.log(`omega=${w} rad/s (omega*dt=${(w * dt).toFixed(3)}): continuous 1%-settle ${(tc * 1000).toFixed(0)} ms | exact-step ${(te * 1000).toFixed(0)} ms | semi-implicit Euler ${(ts * 1000).toFixed(0)} ms`);
}
// frame-rate independence: exact step at dt=1/30 vs 1/240 for omega 42
function pos(omega, h, T) { let x = 1, v = 0; for (let t = 0; t < T - 1e-12; t += h) { const y = omega, j0 = x, j1 = v + j0 * y, e = Math.exp(-y * h); x = e * (j0 + j1 * h); v = e * (v - j1 * y * h); } return x; }
function posE(omega, h, T) { let x = 1, v = 0; for (let t = 0; t < T - 1e-12; t += h) { v += (-omega * omega * x - 2 * omega * v) * h; x += v * h; } return x; }
for (const h of [1 / 30, 1 / 60, 1 / 144, 1 / 240]) console.log(`omega=42, x(0.1s) with step ${(1 / h).toFixed(0)} Hz: exact ${pos(42, h, 0.1).toFixed(4)}  semi-implicit ${posE(42, h, 0.1).toFixed(4)}`);
