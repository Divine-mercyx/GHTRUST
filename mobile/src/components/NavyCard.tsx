import { useId, type PropsWithChildren } from 'react';
import { StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';
import Svg, { Defs, LinearGradient, Path, RadialGradient, Rect, Stop } from 'react-native-svg';

import { colors, radius, shadow, space } from '@/theme/tokens';

type Props = PropsWithChildren<{ style?: StyleProp<ViewStyle>; accessibilityLabel?: string }>;

/**
 * The navy hero card (Home balance, Wallet, Insights): a diagonal navy gradient, a soft cyan
 * glow and two faint waves, drawn with SVG so it stays sharp at any size and needs no images.
 */
export function NavyCard({ children, style, accessibilityLabel }: Props) {
  // Gradient ids are document-wide on web: one per card.
  const id = useId().replace(/[^a-zA-Z0-9]/g, '');
  return (
    <View style={[styles.card, style]} accessibilityLabel={accessibilityLabel}>
      <Svg style={StyleSheet.absoluteFill} viewBox="0 0 100 100" preserveAspectRatio="none" pointerEvents="none">
        <Defs>
          <LinearGradient id={`bg${id}`} x1="0" y1="0" x2="1" y2="1">
            <Stop offset="0" stopColor={colors.navyBright} />
            <Stop offset="0.55" stopColor={colors.navy} />
            <Stop offset="1" stopColor={colors.navyDeep} />
          </LinearGradient>
          <RadialGradient id={`glow${id}`} cx="88" cy="8" r="48" gradientUnits="userSpaceOnUse">
            <Stop offset="0" stopColor={colors.cyan} stopOpacity="0.38" />
            <Stop offset="1" stopColor={colors.cyan} stopOpacity="0" />
          </RadialGradient>
        </Defs>
        <Rect x="0" y="0" width="100" height="100" fill={`url(#bg${id})`} />
        <Rect x="0" y="0" width="100" height="100" fill={`url(#glow${id})`} />
        <Path d="M0 62 C 22 48, 40 78, 62 64 S 92 44, 100 54 L 100 100 L 0 100 Z" fill={colors.white} fillOpacity="0.05" />
        <Path d="M0 80 C 26 68, 46 92, 70 80 S 94 70, 100 76 L 100 100 L 0 100 Z" fill={colors.white} fillOpacity="0.05" />
      </Svg>
      {children}
    </View>
  );
}

/** Text colours on the navy card. */
export const ON_NAVY = { muted: 'rgba(255,255,255,0.72)', faint: 'rgba(255,255,255,0.14)' } as const;

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.navy, // under the SVG while it mounts
    borderRadius: radius.xl,
    padding: space.xl,
    gap: space.sm,
    overflow: 'hidden',
    ...shadow,
  },
});
