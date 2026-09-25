import Ionicons from '@expo/vector-icons/Ionicons';
import { useEffect } from 'react';
import { StyleSheet, View, type DimensionValue, type ViewStyle } from 'react-native';
import Animated, { useAnimatedStyle, useSharedValue, withRepeat, withTiming } from 'react-native-reanimated';

import { messageFor } from '@/api/errors';
import { colors, radius, space } from '@/theme/tokens';

import { Button } from './Button';
import { Card } from './Card';
import { Text } from './Text';

export function Skeleton({ height = 16, width = '100%', style }: { height?: number; width?: DimensionValue; style?: ViewStyle }) {
  const opacity = useSharedValue(0.55);
  useEffect(() => {
    opacity.value = withRepeat(withTiming(1, { duration: 700 }), -1, true);
  }, [opacity]);
  const animated = useAnimatedStyle(() => ({ opacity: opacity.value }));
  return (
    <Animated.View
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={[{ height, width, borderRadius: radius.sm, backgroundColor: colors.surfaceNav }, animated, style]}
    />
  );
}

/** Placeholder with the shape of a typical card while data loads. */
export function CardSkeleton({ lines = 3 }: { lines?: number }) {
  return (
    <Card style={{ gap: space.sm }}>
      <Skeleton height={18} width="45%" />
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} height={14} width={i === lines - 1 ? '60%' : '100%'} />
      ))}
    </Card>
  );
}

export function EmptyState({
  icon,
  title,
  body,
  action,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  title: string;
  body?: string;
  action?: { title: string; onPress: () => void };
}) {
  return (
    <Card style={styles.center}>
      <View style={styles.iconWrap}>
        <Ionicons name={icon} size={26} color={colors.cyanDeep} />
      </View>
      <Text variant="heading" align="center">
        {title}
      </Text>
      {body ? (
        <Text variant="small" muted align="center">
          {body}
        </Text>
      ) : null}
      {action ? <Button title={action.title} onPress={action.onPress} size="sm" style={{ marginTop: space.xs }} /> : null}
    </Card>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <Card style={styles.center}>
      <View style={[styles.iconWrap, { backgroundColor: colors.errorBg }]}>
        <Ionicons name="cloud-offline-outline" size={26} color={colors.error} />
      </View>
      <Text variant="heading" align="center">
        Couldn't load this
      </Text>
      <Text variant="small" muted align="center">
        {messageFor(error)}
      </Text>
      {onRetry ? <Button title="Try again" icon="refresh" variant="secondary" size="sm" onPress={onRetry} /> : null}
    </Card>
  );
}

/** Inline message above a form: errors from the last submit, or a notice. */
export function Banner({ tone = 'error', message }: { tone?: 'error' | 'info' | 'warning'; message: string }) {
  const palette = {
    error: { bg: colors.errorBg, fg: colors.error, icon: 'alert-circle' as const },
    warning: { bg: colors.warningBg, fg: colors.warning, icon: 'warning' as const },
    info: { bg: colors.mint, fg: colors.cyanDeep, icon: 'information-circle' as const },
  }[tone];
  return (
    <View style={[styles.banner, { backgroundColor: palette.bg }]} accessibilityRole="alert" accessibilityLiveRegion="polite">
      <Ionicons name={palette.icon} size={18} color={palette.fg} />
      <Text variant="small" color={palette.fg} style={{ flex: 1 }}>
        {message}
      </Text>
    </View>
  );
}

export function ProgressBar({ value, color = colors.cyan }: { value: number; color?: string }) {
  const pct = Math.max(0, Math.min(1, value));
  return (
    <View
      style={styles.track}
      accessibilityRole="progressbar"
      accessibilityValue={{ min: 0, max: 100, now: Math.round(pct * 100) }}>
      <View style={[styles.fill, { width: `${pct * 100}%`, backgroundColor: color }]} />
    </View>
  );
}

const styles = StyleSheet.create({
  center: { alignItems: 'center', gap: space.xs, paddingVertical: space.xl },
  iconWrap: {
    width: 52,
    height: 52,
    borderRadius: 26,
    backgroundColor: colors.mint,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: space.xs,
  },
  banner: { flexDirection: 'row', gap: space.xs, padding: space.sm, borderRadius: radius.md, alignItems: 'flex-start' },
  track: { height: 8, borderRadius: 4, backgroundColor: colors.surfaceNav, overflow: 'hidden' },
  fill: { height: 8, borderRadius: 4 },
});
