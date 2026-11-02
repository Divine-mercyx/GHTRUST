import { useId, useMemo, useState } from 'react';
import { Pressable, StyleSheet, View, type LayoutChangeEvent } from 'react-native';
import Svg, { Circle, Defs, Line, LinearGradient, Path, Stop } from 'react-native-svg';

import { Text } from '@/components/Text';
import { colors, font, radius, space } from '@/theme/tokens';

export type ChartPoint = { label: string; a: number; b: number };

type Props = {
  points: ChartPoint[];
  /** Selected point (index), shown with a callout; the parent owns it. */
  selected: number;
  onSelect: (index: number) => void;
  height?: number;
};

const PAD_X = 10;
const PAD_TOP = 14;
const PAD_BOTTOM = 8;

/**
 * Two smooth lines on the navy card: `a` (money in, white with a soft fill) and `b` (money
 * out, gold, dashed). Tap or drag across it to move the highlighted point. The curve is
 * monotone, so it never dips below zero or overshoots between points.
 */
export function LineChart({ points, selected, onSelect, height = 150 }: Props) {
  const [width, setWidth] = useState(0);
  const id = useId().replace(/[^a-zA-Z0-9]/g, '');

  const geometry = useMemo(() => {
    if (!width || points.length < 2) return null;
    const max = Math.max(1, ...points.map((p) => Math.max(p.a, p.b)));
    const innerW = width - PAD_X * 2;
    const innerH = height - PAD_TOP - PAD_BOTTOM;
    const x = (i: number) => PAD_X + (innerW * i) / (points.length - 1);
    const y = (v: number) => PAD_TOP + innerH - (innerH * v) / max;
    const a = points.map((p, i) => [x(i), y(p.a)] as const);
    const b = points.map((p, i) => [x(i), y(p.b)] as const);
    const lineA = smoothPath(a);
    return {
      x,
      a,
      b,
      lineA,
      areaA: `${lineA} L ${x(points.length - 1)} ${height} L ${x(0)} ${height} Z`,
      lineB: smoothPath(b),
    };
  }, [width, height, points]);

  const pick = (locationX: number) => {
    if (!width || points.length < 2) return;
    const step = (width - PAD_X * 2) / (points.length - 1);
    onSelect(Math.max(0, Math.min(points.length - 1, Math.round((locationX - PAD_X) / step))));
  };

  const point = geometry ? geometry.a[selected] : null;
  const calloutLeft = point ? Math.max(0, Math.min(width - CALLOUT_W, point[0] - CALLOUT_W / 2)) : 0;

  return (
    <View onLayout={(e: LayoutChangeEvent) => setWidth(e.nativeEvent.layout.width)} style={{ height: height + 34 }}>
      {geometry && point ? (
        <>
          <View style={[styles.callout, { left: calloutLeft }]} pointerEvents="none">
            <Text variant="small" color={colors.navy} style={styles.calloutText} numberOfLines={1}>
              {points[selected].label}
            </Text>
          </View>
          <Pressable
            accessibilityRole="adjustable"
            accessibilityLabel="Chart. Swipe up or down to move between points."
            accessibilityValue={{ text: points[selected].label }}
            accessibilityActions={[{ name: 'increment' }, { name: 'decrement' }]}
            onAccessibilityAction={(e) =>
              onSelect(
                e.nativeEvent.actionName === 'increment'
                  ? Math.min(points.length - 1, selected + 1)
                  : Math.max(0, selected - 1),
              )
            }
            onPress={(e) => pick(e.nativeEvent.locationX)}
            onTouchMove={(e) => pick(e.nativeEvent.locationX)}
            style={{ marginTop: 34 }}>
            <Svg width={width} height={height}>
              <Defs>
                <LinearGradient id={`area${id}`} x1="0" y1="0" x2="0" y2="1">
                  <Stop offset="0" stopColor={colors.white} stopOpacity="0.28" />
                  <Stop offset="1" stopColor={colors.white} stopOpacity="0" />
                </LinearGradient>
              </Defs>
              <Line
                x1={point[0]}
                y1={0}
                x2={point[0]}
                y2={height}
                stroke={colors.white}
                strokeOpacity={0.25}
                strokeWidth={1}
                strokeDasharray="3 4"
              />
              <Path d={geometry.areaA} fill={`url(#area${id})`} />
              <Path d={geometry.lineB} stroke={colors.highlight} strokeWidth={2} strokeDasharray="6 5" fill="none" />
              <Path d={geometry.lineA} stroke={colors.white} strokeWidth={3} strokeLinecap="round" fill="none" />
              <Circle cx={geometry.b[selected][0]} cy={geometry.b[selected][1]} r={4} fill={colors.highlight} />
              <Circle cx={point[0]} cy={point[1]} r={7} fill={colors.navy} stroke={colors.white} strokeWidth={3} />
            </Svg>
          </Pressable>
        </>
      ) : null}
    </View>
  );
}

const CALLOUT_W = 76;

/** Monotone cubic (Fritsch–Carlson) through the points: smooth, never overshoots. */
function smoothPath(pts: readonly (readonly [number, number])[]): string {
  const n = pts.length;
  if (n < 2) return '';
  const dx: number[] = [];
  const slope: number[] = [];
  for (let i = 0; i < n - 1; i++) {
    dx.push(pts[i + 1][0] - pts[i][0]);
    slope.push((pts[i + 1][1] - pts[i][1]) / dx[i]);
  }
  const t: number[] = [slope[0]];
  for (let i = 1; i < n - 1; i++) {
    t.push(slope[i - 1] * slope[i] <= 0 ? 0 : (3 * (dx[i - 1] + dx[i])) / ((2 * dx[i] + dx[i - 1]) / slope[i - 1] + (dx[i] + 2 * dx[i - 1]) / slope[i]));
  }
  t.push(slope[n - 2]);
  let d = `M ${pts[0][0]} ${pts[0][1]}`;
  for (let i = 0; i < n - 1; i++) {
    const h = dx[i] / 3;
    d += ` C ${pts[i][0] + h} ${pts[i][1] + h * t[i]}, ${pts[i + 1][0] - h} ${pts[i + 1][1] - h * t[i + 1]}, ${pts[i + 1][0]} ${pts[i + 1][1]}`;
  }
  return d;
}

const styles = StyleSheet.create({
  callout: {
    position: 'absolute',
    top: 0,
    width: CALLOUT_W,
    height: 28,
    borderRadius: radius.sm,
    backgroundColor: colors.white,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: space.xs,
  },
  calloutText: { fontFamily: font.bold, fontSize: 12, lineHeight: 16 },
});
