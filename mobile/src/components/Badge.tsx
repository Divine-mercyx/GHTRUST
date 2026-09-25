import { StyleSheet, View } from 'react-native';

import type { Tone } from '@/lib/status';
import { colors, radius } from '@/theme/tokens';

import { Text } from './Text';

const TONES: Record<Tone, { bg: string; fg: string }> = {
  neutral: { bg: colors.surfaceNav, fg: colors.textMuted },
  info: { bg: '#E4F3FA', fg: colors.cyanDeep },
  progress: { bg: '#E8ECF7', fg: colors.navy },
  success: { bg: colors.successBg, fg: colors.success },
  warning: { bg: colors.warningBg, fg: colors.warning },
  danger: { bg: colors.errorBg, fg: colors.error },
};

export function Badge({ label, tone = 'neutral' }: { label: string; tone?: Tone }) {
  const t = TONES[tone];
  return (
    <View style={[styles.badge, { backgroundColor: t.bg }]} accessibilityLabel={`Status: ${label}`}>
      <View style={[styles.dot, { backgroundColor: t.fg }]} />
      <Text variant="small" color={t.fg} style={styles.label} numberOfLines={1}>
        {label}
      </Text>
    </View>
  );
}

export const toneColor = (tone: Tone) => TONES[tone].fg;

const styles = StyleSheet.create({
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    alignSelf: 'flex-start',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: radius.pill,
  },
  dot: { width: 6, height: 6, borderRadius: 3 },
  label: { fontSize: 12, lineHeight: 16 },
});
