import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import { Skeleton } from '@/components/States';
import { Text } from '@/components/Text';
import { naira } from '@/lib/format';
import { useInsights } from '@/lib/queries';
import { colors, font, radius, shadow, space } from '@/theme/tokens';

import { PressableScale } from './PressableScale';

/** Home's "Last 30 days" card: money in and out with their share, opening Insights. */
export function MoneySummary() {
  const insights = useInsights('1m');
  if (insights.isError) return null; // Home stays useful without it; Insights explains errors
  const data = insights.data;
  const total = data ? data.money_in + data.money_out : 0;

  return (
    <PressableScale
      scaleTo={0.98}
      accessibilityRole="button"
      accessibilityLabel={
        data
          ? `Last 30 days: ${naira(data.money_in)} in, ${naira(data.money_out)} out. Open insights`
          : 'Open insights'
      }
      onPress={() => router.push('/insights')}
      style={styles.card}>
      <View style={styles.head}>
        <Text variant="bodyStrong">Last 30 days</Text>
        <View style={styles.link}>
          <Text variant="small" color={colors.cyanDeep} style={{ fontFamily: font.semibold }}>
            Insights
          </Text>
          <Ionicons name="chevron-forward" size={14} color={colors.cyanDeep} />
        </View>
      </View>
      {data ? (
        <View style={styles.rows}>
          <Line label="Money in" icon="arrow-down" amount={data.money_in} share={total ? data.money_in / total : 0} tone={colors.yield} />
          <Line label="Money out" icon="arrow-up" amount={data.money_out} share={total ? data.money_out / total : 0} tone={colors.navy} />
        </View>
      ) : (
        <View style={styles.rows}>
          <Skeleton height={14} width="80%" />
          <Skeleton height={14} width="65%" />
        </View>
      )}
    </PressableScale>
  );
}

function Line({
  label,
  icon,
  amount,
  share,
  tone,
}: {
  label: string;
  icon: keyof typeof Ionicons.glyphMap;
  amount: number;
  share: number;
  tone: string;
}) {
  return (
    <View style={styles.line}>
      <View style={[styles.icon, { backgroundColor: `${tone}14` }]}>
        <Ionicons name={icon} size={14} color={tone} />
      </View>
      <View style={{ flex: 1, gap: 6 }}>
        <View style={styles.lineHead}>
          <Text variant="small" muted>
            {label}
          </Text>
          <Text variant="small" style={{ fontFamily: font.bold }}>
            {naira(amount)}
          </Text>
        </View>
        <View style={styles.track}>
          <View style={[styles.fill, { width: `${Math.round(share * 100)}%` }]} />
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { backgroundColor: colors.card, borderRadius: radius.lg, padding: space.md, gap: space.md, ...shadow },
  head: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  link: { flexDirection: 'row', alignItems: 'center', gap: 2 },
  rows: { gap: space.sm },
  line: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  icon: { width: 28, height: 28, borderRadius: 14, alignItems: 'center', justifyContent: 'center' },
  lineHead: { flexDirection: 'row', justifyContent: 'space-between' },
  track: { height: 6, borderRadius: 3, backgroundColor: colors.slateFill, overflow: 'hidden' },
  fill: { height: 6, borderRadius: 3, backgroundColor: colors.highlight },
});
