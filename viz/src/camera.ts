// Pan/zoom camera. The camera never jumps to where it is told: it has a target
// (center and log-zoom) and follows it as a critically damped spring,
//   a = omega^2 (target - x) - 2 omega v,
// integrated with semi-implicit Euler on the same fixed timestep as the particles.
// Wheel zoom moves the target around the cursor; the camera then follows physically.
// Under prefers-reduced-motion every change is an instant cut (state = target).

import { PHYSICS } from "./physics.js";

export const CAMERA = Object.freeze({
  /** Follow stiffness (rad/s) for zoom, fly-to and fit. */
  omega: 9,
  /** Follow stiffness while a pointer drags the view (tight, still a spring). */
  omegaDrag: 42,
  dt: PHYSICS.dt,
  maxFrameSeconds: 0.1,
  maxStepsPerFrame: 24,
  /** Zoom per wheel delta pixel: factor = exp(-deltaY * wheelZoom). */
  wheelZoom: 0.0016,
  /** Arrow keys move the target by this fraction of the viewport. */
  keyPanFraction: 0.12,
  /** Zoom limits relative to the fit-to-data zoom. */
  minZoomFactor: 0.3,
  maxZoomFactor: 40,
  /** Padding around the data when fitting, CSS px. */
  fitPadding: 56,
  /** At rest when within these (screen px, screen px/s). */
  restPx: 0.05,
  restSpeedPx: 0.5,
});

export class Camera {
  /** Center (world units) and natural-log zoom; scale = exp(z) screen px per world unit. */
  x = 0;
  y = 0;
  z = 0;
  vx = 0;
  vy = 0;
  vz = 0;
  tx = 0;
  ty = 0;
  tz = 0;
  /** Viewport, CSS px. */
  width = 1;
  height = 1;
  omega: number = CAMERA.omega;
  minZ = Math.log(1e-3);
  maxZ = Math.log(1e3);
  /** World bounds the target center is kept near (so the field cannot be lost). */
  private bx0 = -1e6;
  private bx1 = 1e6;
  private by0 = -1e6;
  private by1 = 1e6;
  resting = true;
  /** Reduced motion: every target change is applied as a cut. */
  instant = false;
  private accumulator = 0;

  get scale(): number {
    return Math.exp(this.z);
  }
  get targetScale(): number {
    return Math.exp(this.tz);
  }

  setViewport(width: number, height: number): void {
    this.width = Math.max(1, width);
    this.height = Math.max(1, height);
  }

  /** Zoom limits and pan bounds from the fit-to-data zoom and the data bounds. */
  setLimits(fitScale: number, x0: number, y0: number, x1: number, y1: number): void {
    this.minZ = Math.log(Math.max(1e-6, fitScale * CAMERA.minZoomFactor));
    this.maxZ = Math.log(Math.max(fitScale * CAMERA.maxZoomFactor, 6));
    const mx = (x1 - x0) * 0.5 + 200;
    const my = (y1 - y0) * 0.5 + 200;
    this.bx0 = x0 - mx;
    this.bx1 = x1 + mx;
    this.by0 = y0 - my;
    this.by1 = y1 + my;
  }

  screenToWorldX(sx: number): number {
    return this.x + (sx - this.width / 2) / this.scale;
  }
  screenToWorldY(sy: number): number {
    return this.y + (sy - this.height / 2) / this.scale;
  }
  worldToScreenX(wx: number): number {
    return (wx - this.x) * this.scale + this.width / 2;
  }
  worldToScreenY(wy: number): number {
    return (wy - this.y) * this.scale + this.height / 2;
  }

  private clampTarget(): void {
    this.tz = Math.min(this.maxZ, Math.max(this.minZ, this.tz));
    this.tx = Math.min(this.bx1, Math.max(this.bx0, this.tx));
    this.ty = Math.min(this.by1, Math.max(this.by0, this.ty));
  }

  private retarget(): void {
    this.clampTarget();
    this.resting = false;
    if (this.instant) this.cut();
  }

  /** Move the target (world center, screen px per world unit). */
  setTarget(x: number, y: number, scale: number = this.targetScale): void {
    this.tx = x;
    this.ty = y;
    this.tz = Math.log(Math.max(1e-9, scale));
    this.retarget();
  }

  /** Jump the camera to its target with zero velocity: a cut, not a transition. */
  cut(): void {
    this.clampTarget();
    this.x = this.tx;
    this.y = this.ty;
    this.z = this.tz;
    this.vx = this.vy = this.vz = 0;
    this.resting = true;
  }

  /** Zoom the target by `factor` around a screen point (the point under the cursor stays put). */
  zoomAt(sx: number, sy: number, factor: number): void {
    const wx = this.screenToWorldX(sx);
    const wy = this.screenToWorldY(sy);
    this.tz = Math.min(this.maxZ, Math.max(this.minZ, this.tz + Math.log(factor)));
    const s = Math.exp(this.tz);
    this.tx = wx - (sx - this.width / 2) / s;
    this.ty = wy - (sy - this.height / 2) / s;
    this.retarget();
  }

  /** Pan the target by a screen-space offset. */
  panBy(dxScreen: number, dyScreen: number): void {
    const s = this.targetScale;
    this.tx += dxScreen / s;
    this.ty += dyScreen / s;
    this.retarget();
  }

  /** Keep a grabbed world point under the pointer (drag-to-pan). */
  holdPoint(wx: number, wy: number, sx: number, sy: number): void {
    const s = this.targetScale;
    this.tx = wx - (sx - this.width / 2) / s;
    this.ty = wy - (sy - this.height / 2) / s;
    this.retarget();
  }

  /** Screen insets (CSS px) the fit keeps clear, e.g. under an overlay spanning the view. */
  insetTop = 0;
  insetBottom = 0;

  /** Scale that fits a world box into the viewport, less padding and insets. */
  fitScale(x0: number, y0: number, x1: number, y1: number): number {
    const pad = CAMERA.fitPadding;
    const w = Math.max(1, x1 - x0);
    const h = Math.max(1, y1 - y0);
    const availW = Math.max(40, this.width - 2 * pad);
    const availH = Math.max(40, this.height - 2 * pad - this.insetTop - this.insetBottom);
    return Math.max(1e-6, Math.min(availW / w, availH / h));
  }

  /** Target that fits a world box (centered in the area left free by the insets). */
  fitTarget(x0: number, y0: number, x1: number, y1: number): { x: number; y: number; scale: number } {
    const scale = this.fitScale(x0, y0, x1, y1);
    return { x: (x0 + x1) / 2, y: (y0 + y1) / 2 + (this.insetBottom - this.insetTop) / 2 / scale, scale };
  }

  /** Integrate the follow spring for one frame; returns true if the view moved. */
  advance(frameSeconds: number): boolean {
    if (this.resting) {
      this.accumulator = 0;
      return false;
    }
    const dt = CAMERA.dt;
    this.accumulator += Math.min(Math.max(frameSeconds, 0), CAMERA.maxFrameSeconds);
    let steps = 0;
    while (this.accumulator >= dt && steps < CAMERA.maxStepsPerFrame) {
      this.step(dt);
      this.accumulator -= dt;
      steps++;
    }
    if (steps >= CAMERA.maxStepsPerFrame) this.accumulator = 0;
    // At rest when the remaining error and speed are sub-pixel on screen.
    const s = this.scale;
    const err = Math.max(Math.abs(this.tx - this.x) * s, Math.abs(this.ty - this.y) * s, Math.abs(this.tz - this.z) * 1000);
    const speed = Math.max(Math.abs(this.vx) * s, Math.abs(this.vy) * s, Math.abs(this.vz) * 1000);
    if (err < CAMERA.restPx && speed < CAMERA.restSpeedPx) {
      this.x = this.tx;
      this.y = this.ty;
      this.z = this.tz;
      this.vx = this.vy = this.vz = 0;
      this.resting = true;
    }
    return steps > 0;
  }

  private step(dt: number): void {
    const w = this.omega;
    const k = w * w;
    const c = 2 * w;
    this.vx += (k * (this.tx - this.x) - c * this.vx) * dt;
    this.vy += (k * (this.ty - this.y) - c * this.vy) * dt;
    this.vz += (k * (this.tz - this.z) - c * this.vz) * dt;
    this.x += this.vx * dt;
    this.y += this.vy * dt;
    this.z += this.vz * dt;
  }
}
