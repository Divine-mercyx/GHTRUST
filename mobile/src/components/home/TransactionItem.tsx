import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { memo } from 'react';
import { StyleSheet, View } from 'react-native';

import { Badge, toneColor } from '@/components/Badge';
import { Text } from '@/components/Text';
import { activityWhen, type Activity } from '@/lib/activity';
import { naira } from '@/lib/format';
import { colors, radius, space } from '@/theme/tokens';

import { PressableScale } from './PressableScale';

/** Fixed row height, so lists of these never re-measure while scrolling. */
export const TRANSACTION_ROW_HEIGHT = 76;

type Props = {
  item: Activity;
  last?: boolean;
  /** Add the time of day ("Today, 2:05 pm"), for full history lists. */
  withTime?: boolean;
};

/** A row in "Recent activity": category icon, title and detail, amount, status and when. */
export const TransactionItem = memo(function TransactionItem({ item, last, withTime }: Props) {
  const tint = toneColor(item.status.tone);
  const when = activityWhen(item.at, new Date(), withTime);
  const sign = item.direction === 'in' ? '+' : item.direction === 'out' ? '−' : '';
  const amount = item.amount ? `${sign}${naira(item.amount)}` : null;
  return (
    <PressableScale
      scaleTo={0.98}
      accessibilityRole="button"
      accessibilityLabel={`${item.title}. ${amount ?? ''}. ${item.status.label}. ${when}`}
      onPress={() => router.push(item.href)}
      style={[styles.row, !last && styles.divider]}>
      <View style={[styles.icon, { backgroundColor: `${tint}14` }]}>
        <Ionicons name={item.icon} size={20} color={tint} />
      </View>
      <View style={styles.body}>
        <Text variant="bodyStrong" numberOfLines={1}>
          {item.title}
        </Text>
        <Text variant="small" muted numberOfLines={1}>
          {when ? `${when} · ` : ''}
          {item.subtitle}
        </Text>
      </View>
      <View style={styles.side}>
        {amount ? (
          <Text variant="bodyStrong" color={item.direction === 'in' ? colors.yield : colors.text} numberOfLines={1}>
            {amount}
          </Text>
        ) : null}
        <Badge label={item.status.label} tone={item.status.tone} />
      </View>
    </PressableScale>
  );
});

const styles = StyleSheet.create({
  row: {
    height: TRANSACTION_ROW_HEIGHT,
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
    paddingHorizontal: space.md,
    backgroundColor: colors.card,
  },
  divider: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  icon: { width: 42, height: 42, borderRadius: radius.md, alignItems: 'center', justifyContent: 'center' },
  body: { flex: 1, gap: 2 },
  side: { alignItems: 'flex-end', gap: 4, maxWidth: '42%' },
});
