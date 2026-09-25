// Uniform screen-space grids: nearest-particle hit testing and greedy label placement.

/** Buckets points (screen px) for nearest-point queries within a radius. */
export class PointGrid {
  private cell = 24;
  private cols = 1;
  private rows = 1;
  private heads: Int32Array = new Int32Array(1);
  private next: Int32Array = new Int32Array(0);

  build(xs: Float32Array, ys: Float32Array, visible: Uint8Array, n: number, width: number, height: number, cell: number): void {
    this.cell = cell;
    this.cols = Math.max(1, Math.ceil(width / cell));
    this.rows = Math.max(1, Math.ceil(height / cell));
    const size = this.cols * this.rows;
    if (this.heads.length < size) this.heads = new Int32Array(size);
    this.heads.fill(-1, 0, size);
    if (this.next.length < n) this.next = new Int32Array(n);
    for (let i = 0; i < n; i++) {
      if (!visible[i]) continue;
      const cx = Math.floor(xs[i] / cell);
      const cy = Math.floor(ys[i] / cell);
      if (cx < 0 || cy < 0 || cx >= this.cols || cy >= this.rows) continue;
      const c = cy * this.cols + cx;
      this.next[i] = this.heads[c];
      this.heads[c] = i;
    }
  }

  /**
   * The particle whose center is nearest to (px, py), if that distance is within
   * max(radius, its drawn radius + 4); -1 otherwise.
   */
  nearest(px: number, py: number, radius: number, xs: Float32Array, ys: Float32Array, rs: Float32Array): number {
    const reach = Math.ceil(radius / this.cell) + 1;
    const cx = Math.floor(px / this.cell);
    const cy = Math.floor(py / this.cell);
    let best = -1;
    let bestD = Infinity;
    for (let gy = Math.max(0, cy - reach); gy <= Math.min(this.rows - 1, cy + reach); gy++) {
      for (let gx = Math.max(0, cx - reach); gx <= Math.min(this.cols - 1, cx + reach); gx++) {
        for (let i = this.heads[gy * this.cols + gx]; i !== -1; i = this.next[i]) {
          const d = Math.hypot(xs[i] - px, ys[i] - py);
          const limit = Math.max(radius, rs[i] + 4);
          if (d <= limit && d < bestD) {
            bestD = d;
            best = i;
          }
        }
      }
    }
    return best;
  }
}

/** Rectangles placed so far, bucketed by cell; used to keep labels from overlapping. */
export class RectGrid {
  private cell = 48;
  private cols = 1;
  private rows = 1;
  private buckets: number[][] = [];
  private rects: number[] = [];

  reset(width: number, height: number, cell = 48): void {
    this.cell = cell;
    this.cols = Math.max(1, Math.ceil(width / cell));
    this.rows = Math.max(1, Math.ceil(height / cell));
    const size = this.cols * this.rows;
    if (this.buckets.length < size) {
      for (let k = this.buckets.length; k < size; k++) this.buckets.push([]);
    }
    for (let k = 0; k < size; k++) this.buckets[k]!.length = 0;
    this.rects.length = 0;
  }

  private range(x0: number, y0: number, x1: number, y1: number): [number, number, number, number] {
    const c = this.cell;
    return [
      Math.max(0, Math.floor(x0 / c)),
      Math.max(0, Math.floor(y0 / c)),
      Math.min(this.cols - 1, Math.floor(x1 / c)),
      Math.min(this.rows - 1, Math.floor(y1 / c)),
    ];
  }

  collides(x0: number, y0: number, x1: number, y1: number): boolean {
    const [gx0, gy0, gx1, gy1] = this.range(x0, y0, x1, y1);
    const r = this.rects;
    for (let gy = gy0; gy <= gy1; gy++) {
      for (let gx = gx0; gx <= gx1; gx++) {
        for (const k of this.buckets[gy * this.cols + gx]!) {
          if (x0 < r[k + 2]! && x1 > r[k]! && y0 < r[k + 3]! && y1 > r[k + 1]!) return true;
        }
      }
    }
    return false;
  }

  add(x0: number, y0: number, x1: number, y1: number): void {
    const k = this.rects.length;
    this.rects.push(x0, y0, x1, y1);
    const [gx0, gy0, gx1, gy1] = this.range(x0, y0, x1, y1);
    for (let gy = gy0; gy <= gy1; gy++) {
      for (let gx = gx0; gx <= gx1; gx++) this.buckets[gy * this.cols + gx]!.push(k);
    }
  }
}
