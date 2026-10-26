/**
 * The network modal's chart: the last 30 per-second samples of each direction
 * as a smoothed line with a soft area under it, in a 300×90 box. Pure maths,
 * no DOM -- the component only hands the paths to <path d>.
 */
export const CHART_W = 300;

export const CHART_H = 90;

export const BASELINE = 86; // y of value 0

export const KEEP = 30; // samples across the full width

export const TOP = 6; // y of the peak when the scale is stretched

export type Point = [number, number];

/** 0.8 px per Mbps until the peak passes 100, then the peak sits at the top. */
export function yScale(peak: number): number {
  return peak > 100 ? (BASELINE - TOP) / peak : 0.8;
}

/** The newest sample is at the right edge; a tape shorter than KEEP is spread over the full width. */
export function toPoints(values: number[], scale: number): Point[] {
  const n = values.length;
  const step = CHART_W / (Math.max(n, 2) - 1);
  return values.map((v, i) => {
    const x = CHART_W - (n - 1 - i) * step;
    const y = Math.max(TOP, BASELINE - Math.max(0, v) * scale);
    return [round(x), round(y)];
  });
}

const round = (n: number) => Math.round(n * 100) / 100;

/** A cubic through the midpoints: each segment's handles sit at the half-way x, level with its ends. */
export function linePath(pts: Point[]): string {
  const first = pts[0];
  if (pts.length < 2 || !first) return '';
  let d = `M${first[0]},${first[1]}`;
  for (let i = 1; i < pts.length; i++) {
    const [x0, y0] = pts[i - 1] as Point;
    const [x1, y1] = pts[i] as Point;
    const mx = round((x0 + x1) / 2);
    d += ` C${mx},${y0} ${mx},${y1} ${x1},${y1}`;
  }
  return d;
}

export function areaPath(pts: Point[]): string {
  const line = linePath(pts);
  const first = pts[0];
  const last = pts[pts.length - 1];
  if (!line || !first || !last) return '';
  return `${line} L${last[0]},${BASELINE} L${first[0]},${BASELINE} Z`;
}
