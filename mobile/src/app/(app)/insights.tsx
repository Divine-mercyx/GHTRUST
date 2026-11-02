import Ionicons from '@expo/vector-icons/Ionicons';
import { useMemo, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import Animated, { FadeIn } from 'react-native-reanimated';

import type { InsightRange, WalletInsights } from '@/api/types';
import { Card, SectionHeader } from '@/components/Card';
import { PressableScale } from '@/components/home/PressableScale';
import { LineChart, type ChartPoint } from '@/components/insights/LineChart';
import { NavyCard, ON_NAVY } from '@/components/NavyCard';
import { Screen } from '@/components/Screen';
import { CardSkeleton, ErrorState } from '@/components/States';
import { Text } from '@/components/Text';
import { transactionIcon } from '@/lib/activity';
import { chartLabel, naira } from '@/lib/format';
import { useInsights } from '@/lib/queries';
import { colors, font, radius, shadow, space } from '@/theme/tokens';

const RANGES: { value: InsightRange; label: string }[] = [
  { value: '1m', label: '1m' },
  { value: '6m', label: '6m' },
  { value: '12m', label: '12m' },
];

const KIND_LABEL: Record<WalletInsights['categories'][number]['kind'], string> = {
  funding: 'Money added',
  loan_payout: 'Loans paid to you',
  investment_payout: 'Investments paid out',
  repayment: 'Loan repayments',
  withdrawal: 'Sent to bank',
  investment: 'Invested',
};

/** Money in and out of the wallet over a month, 6 or 12 months: chart, totals and what it was. */
export default function Insights() {
  const [range, setRange] = useState<InsightRange>('6m');
  const insights = useInsights(range);
  const data = insights.data;

  return (
    <Screen edges={['bottom']} onRefresh={() => insights.refetch()} refreshing={insights.isRefetching}>
      <View style={styles.ranges} accessibilityRole="tablist">
        {RANGES.map((r) => {
          const on = r.value === range;
          return (
            <PressableScale
              key={r.value}
              accessibilityRole="tab"
              accessibilityState={{ selected: on }}
              accessibilityLabel={r.value === '1m' ? 'Last month' : `Last ${r.value.replace('m', '')} months`}
              onPress={() => setRange(r.value)}
              style={[styles.range, on && styles.rangeOn]}>
              <Text variant="small" color={colors.navy} style={{ fontFamily: on ? font.bold : font.semibold }}>
                {r.label}
              </Text>
            </PressableScale>
          );
        })}
        {data ? (
          <Text variant="small" muted style={styles.period} numberOfLines={1}>
            {periodLabel(data)}
          </Text>
        ) : null}
      </View>

      {insights.isPending ? (
        <CardSkeleton lines={4} />
      ) : insights.isError || !data ? (
        <ErrorState error={insights.error} onRetry={() => insights.refetch()} />
      ) : (
        <Animated.View key={range} entering={FadeIn.duration(220)} style={{ gap: space.md }}>
          <Hero data={data} />
          <Split data={data} />
          <Categories data={data} />
        </Animated.View>
      )}
    </Screen>
  );
}

function Hero({ data }: { data: WalletInsights }) {
  const byDay = data.range === '1m';
  const points: ChartPoint[] = useMemo(
    () =>
      data.series.map((p) => ({
        label: chartLabel(p.start, byDay ? 'day' : 'month'),
        a: p.money_in,
        b: p.money_out,
      })),
    [data.series, byDay],
  );
  const lastActive = useMemo(() => {
    for (let i = data.series.length - 1; i >= 0; i--) {
      if (data.series[i].money_in || data.series[i].money_out) return i;
    }
    return data.series.length - 1;
  }, [data.series]);
  // The card remounts when the range changes (keyed by range), which resets this.
  const [picked, setSelected] = useState(lastActive);
  const selected = Math.min(picked, data.series.length - 1);
  const point = data.series[selected];
  const empty = data.money_in === 0 && data.money_out === 0;

  return (
    <NavyCard>
      <View style={styles.totals}>
        <View style={{ flex: 1 }}>
          <Text variant="small" color={ON_NAVY.muted}>
            Money in
          </Text>
          <Text variant="title" color={colors.white} numberOfLines={1} adjustsFontSizeToFit style={{ fontFamily: font.extrabold }}>
            {naira(data.money_in)}
          </Text>
        </View>
        <View style={{ flex: 1, alignItems: 'flex-end' }}>
          <Text variant="small" color={ON_NAVY.muted}>
            Money out
          </Text>
          <Text variant="title" color={ON_NAVY.muted} numberOfLines={1} adjustsFontSizeToFit>
            {naira(data.money_out)}
          </Text>
        </View>
      </View>

      {empty ? (
        <View style={styles.emptyChart}>
          <Ionicons name="analytics-outline" size={28} color={ON_NAVY.muted} />
          <Text variant="small" color={ON_NAVY.muted} align="center">
            No money in or out of your wallet in this period yet.
          </Text>
        </View>
      ) : (
        <>
          <LineChart points={points} selected={selected} onSelect={setSelected} />
          <View style={styles.legend}>
            <Legend color={colors.white} label={`In ${naira(point.money_in)}`} />
            <Legend color={colors.highlight} dashed label={`Out ${naira(point.money_out)}`} />
          </View>
        </>
      )}
    </NavyCard>
  );
}

function Legend({ color, label, dashed }: { color: string; label: string; dashed?: boolean }) {
  return (
    <View style={styles.legendItem}>
      <View style={[styles.legendSwatch, { borderColor: color, borderStyle: dashed ? 'dashed' : 'solid' }]} />
      <Text variant="small" color={colors.white} style={{ fontFamily: font.semibold }}>
        {label}
      </Text>
    </View>
  );
}

/** In vs out as shares of everything that moved. */
function Split({ data }: { data: WalletInsights }) {
  const total = data.money_in + data.money_out;
  if (!total) return null;
  const rows = [
    { label: 'Money in', icon: 'arrow-down' as const, tone: colors.yield, amount: data.money_in },
    { label: 'Money out', icon: 'arrow-up' as const, tone: colors.navy, amount: data.money_out },
  ];
  const net = data.money_in - data.money_out;
  return (
    <Card style={{ gap: space.md }}>
      <View style={styles.splitHead}>
        <Text variant="bodyStrong">In vs out</Text>
        <Text variant="small" color={net >= 0 ? colors.yield : colors.text} style={{ fontFamily: font.bold }}>
          {net >= 0 ? '+' : '−'}
          {naira(Math.abs(net))} net
        </Text>
      </View>
      {rows.map((r) => {
        const share = Math.round((r.amount / total) * 100);
        return (
          <View key={r.label} style={styles.splitRow}>
            <View style={[styles.splitIcon, { backgroundColor: `${r.tone}14` }]}>
              <Ionicons name={r.icon} size={16} color={r.tone} />
            </View>
            <View style={{ flex: 1, gap: 6 }}>
              <View style={styles.splitLine}>
                <Text variant="small" style={{ fontFamily: font.semibold }}>
                  {r.label}
                </Text>
                <Text variant="small" style={{ fontFamily: font.bold }}>
                  {share}%
                </Text>
              </View>
              <View style={styles.track}>
                <View style={[styles.fill, { width: `${share}%` }]} />
              </View>
            </View>
          </View>
        );
      })}
    </Card>
  );
}

function Categories({ data }: { data: WalletInsights }) {
  if (!data.categories.length) return null;
  return (
    <View>
      <SectionHeader title="Where it came from and went" />
      <View style={styles.list}>
        {data.categories.map((c, i) => (
          <View key={`${c.kind}-${c.direction}`} style={[styles.catRow, i < data.categories.length - 1 && styles.divider]}>
            <View style={[styles.catIcon, { backgroundColor: c.direction === 'in' ? colors.yieldBg : colors.surfaceNav }]}>
              <Ionicons name={transactionIcon(c.kind)} size={18} color={c.direction === 'in' ? colors.yield : colors.navy} />
            </View>
            <View style={{ flex: 1 }}>
              <Text variant="bodyStrong" numberOfLines={1}>
                {KIND_LABEL[c.kind]}
              </Text>
              <Text variant="small" muted>
                {c.count} {c.count === 1 ? 'transaction' : 'transactions'}
              </Text>
            </View>
            <Text variant="bodyStrong" color={c.direction === 'in' ? colors.yield : colors.text}>
              {c.direction === 'in' ? '+' : '−'}
              {naira(c.amount)}
            </Text>
          </View>
        ))}
      </View>
    </View>
  );
}

function periodLabel(data: WalletInsights): string {
  if (data.range === '1m') return `${chartLabel(data.start, 'day')} to ${chartLabel(data.end, 'day')}`;
  return `${chartLabel(data.start, 'month', true)} to ${chartLabel(data.end, 'month', true)}`;
}

const styles = StyleSheet.create({
  ranges: { flexDirection: 'row', alignItems: 'center', gap: space.xs },
  range: {
    minWidth: 52,
    height: 38,
    paddingHorizontal: space.md,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
    alignItems: 'center',
    justifyContent: 'center',
  },
  rangeOn: { backgroundColor: colors.highlight, borderColor: colors.highlight },
  period: { flex: 1, textAlign: 'right' },
  totals: { flexDirection: 'row', gap: space.md },
  emptyChart: { alignItems: 'center', gap: space.xs, paddingVertical: space.xxl },
  legend: { flexDirection: 'row', gap: space.lg, justifyContent: 'center' },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  legendSwatch: { width: 18, height: 0, borderTopWidth: 3 },
  splitHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  splitRow: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  splitIcon: { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center' },
  splitLine: { flexDirection: 'row', justifyContent: 'space-between' },
  track: { height: 8, borderRadius: 4, backgroundColor: colors.slateFill, overflow: 'hidden' },
  fill: { height: 8, borderRadius: 4, backgroundColor: colors.highlight },
  list: { backgroundColor: colors.card, borderRadius: radius.lg, overflow: 'hidden', ...shadow },
  catRow: { flexDirection: 'row', alignItems: 'center', gap: space.sm, padding: space.md },
  catIcon: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
  divider: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
});
