import { BASELINE, CHART_W, KEEP, TOP, areaPath, linePath, toPoints, yScale, type Point } from './netchart';

const at = (pts: Point[], i: number) => pts[i] as Point;

describe('netchart', () => {
  it('scales 0.8 px per Mbps until the peak passes 100, then fits the peak to the top', () => {
    expect(yScale(73)).toBe(0.8);
    expect(yScale(100)).toBe(0.8);
    expect(at(toPoints([100], yScale(100)), 0)[1]).toBe(BASELINE - 80);
    expect(at(toPoints([250], yScale(250)), 0)[1]).toBe(TOP);
  });

  it('spreads a short tape over the width, the newest sample at the right edge', () => {
    const three = toPoints([1, 2, 3], 0.8);
    expect(at(three, 2)[0]).toBe(CHART_W);
    expect(at(three, 0)[0]).toBe(0);
    expect(at(three, 1)[0]).toBe(CHART_W / 2);
    const full = toPoints(Array(KEEP).fill(1), 0.8);
    expect(at(full, 0)[0]).toBe(0);
    expect(at(full, KEEP - 1)[0]).toBe(CHART_W);
  });

  it('draws nothing from a single sample and a smoothed cubic from two or more', () => {
    expect(linePath(toPoints([5], 0.8))).toBe('');
    const d = linePath(toPoints([0, 10], 0.8));
    expect(d.startsWith('M')).toBe(true);
    expect(d).toContain(' C');
    expect(d.endsWith(`${CHART_W},${BASELINE - 8}`)).toBe(true);
    const a = areaPath(toPoints([0, 10], 0.8));

    expect(a.endsWith(`L${CHART_W},${BASELINE} L${at(toPoints([0, 10], 0.8), 0)[0]},${BASELINE} Z`)).toBe(
      true,
    );
  });
});
