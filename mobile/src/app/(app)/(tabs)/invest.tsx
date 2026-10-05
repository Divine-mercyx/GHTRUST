import Ionicons from '@expo/vector-icons/Ionicons';
import { Image } from 'expo-image';
import { router } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import type { Investment, InvestmentPlan } from '@/api/types';
import { Badge } from '@/components/Badge';
import { Card, SectionHeader } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { Banner, CardSkeleton, EmptyState, ErrorState, ProgressBar } from '@/components/States';
import { Text } from '@/components/Text';
import { date, naira } from '@/lib/format';
import { planImage, progress, RISK } from '@/lib/investments';
import { useFeatures, useInvestmentPlans, useMyInvestments } from '@/lib/queries';
import { colors, font, radius, shadow, space } from '@/theme/tokens';

/** Plans to put wallet money into, and the customer's own investments. */
export default function InvestTab() {
  const { investments: open } = useFeatures();
  const plans = useInvestmentPlans();
  const mine = useMyInvestments();
  const active = (mine.data ?? []).filter((i) => i.status === 'active');
  const invested = active.reduce((sum, i) => sum + Number(i.amount), 0);
  const returns = active.reduce((sum, i) => sum + Number(i.projected_return), 0);

  return (
    <Screen
      onRefresh={() => {
        plans.refetch();
        mine.refetch();
      }}
      refreshing={plans.isRefetching || mine.isRefetching}>
      <Text variant="title">Invest</Text>
      {!open ? <Banner tone="info" message="Investing opens soon. You can already look through the plans." /> : null}

      <View style={styles.summary}>
        <View pointerEvents="none" style={styles.glow} />
        <Text variant="caption" color={colors.cyan}>
          INVESTED
        </Text>
        <Text variant="display" color={colors.white}>
          {naira(invested)}
        </Text>
        <View style={styles.summaryRow}>
          <Ionicons name="trending-up" size={16} color={colors.yieldBright} />
          <Text variant="small" color={colors.yieldBright} style={{ fontFamily: font.semibold }}>
            +{naira(returns)} expected returns
          </Text>
        </View>
        <Text variant="small" color="rgba(255,255,255,0.7)">
          {active.length === 0
            ? 'Choose a plan below to start.'
            : `${active.length} active ${active.length === 1 ? 'investment' : 'investments'} · paid into your wallet at maturity`}
        </Text>
      </View>

      {mine.data && mine.data.length > 0 ? (
        <>
          <SectionHeader title="Your investments" />
          <View style={{ gap: space.sm }}>
            {mine.data.map((inv) => (
              <Holding key={inv.id} inv={inv} />
            ))}
          </View>
        </>
      ) : null}

      <SectionHeader title="Plans" />
      {plans.isPending ? (
        <CardSkeleton lines={3} />
      ) : plans.isError ? (
        <ErrorState error={plans.error} onRetry={() => plans.refetch()} />
      ) : (plans.data ?? []).length === 0 ? (
        <EmptyState icon="leaf-outline" title="No plans yet" body="New investment plans will show up here." />
      ) : (
        <View style={{ gap: space.md }}>
          {plans.data!.map((p) => (
            <PlanCard key={p.id} plan={p} />
          ))}
        </View>
      )}
      <Text variant="small" muted style={{ marginTop: space.md }}>
        Returns are fixed when you invest. Your money is locked until the plan matures, then the amount plus returns
        goes into your wallet automatically.
      </Text>
    </Screen>
  );
}

function PlanCard({ plan }: { plan: InvestmentPlan }) {
  const image = planImage(plan);
  const risk = RISK[plan.risk] ?? RISK.low;
  return (
    <Card style={styles.plan} onPress={() => router.push(`/invest/${plan.id}`)} accessibilityLabel={`${plan.name}, ${Number(plan.return_rate)}% a year`}>
      <View style={styles.planArt}>
        {image ? (
          <Image source={{ uri: image }} style={StyleSheet.absoluteFill} contentFit="cover" transition={200} />
        ) : (
          <Ionicons name="leaf" size={44} color="rgba(255,255,255,0.22)" style={styles.planIcon} />
        )}
        <View style={styles.rate}>
          <Text variant="small" color={colors.yield} style={{ fontFamily: font.bold }}>
            {Number(plan.return_rate)}% a year
          </Text>
        </View>
      </View>
      <View style={styles.planBody}>
        <Text variant="heading" numberOfLines={1}>
          {plan.name}
        </Text>
        <Text variant="small" muted>
          {plan.tenure_months} months · from {naira(plan.min_amount)}
        </Text>
        <View style={styles.planFoot}>
          <Badge label={risk.label} tone={risk.tone} />
          <Ionicons name="chevron-forward" size={18} color={colors.textFaint} />
        </View>
      </View>
    </Card>
  );
}

function Holding({ inv }: { inv: Investment }) {
  const done = inv.status !== 'active';
  return (
    <Card style={{ gap: space.xs }}>
      <View style={styles.holdHead}>
        <Text variant="bodyStrong" numberOfLines={1} style={{ flex: 1 }}>
          {inv.plan_name}
        </Text>
        <Badge label={done ? 'Paid out' : 'Active'} tone={done ? 'success' : 'info'} />
      </View>
      <View style={styles.holdHead}>
        <Text variant="title">{naira(inv.amount)}</Text>
        <Text variant="bodyStrong" color={colors.yield}>
          +{naira(inv.projected_return)}
        </Text>
      </View>
      <ProgressBar value={progress(inv)} color={colors.yield} />
      <Text variant="small" muted>
        {done
          ? `${naira(inv.maturity_value)} paid into your wallet ${date(inv.paid_out_at ?? inv.maturity_date)}`
          : `${naira(inv.maturity_value)} on ${date(inv.maturity_date)} · ${Number(inv.return_rate)}% a year`}
      </Text>
    </Card>
  );
}

const styles = StyleSheet.create({
  summary: {
    backgroundColor: colors.navy,
    borderRadius: radius.xl,
    padding: space.xl,
    gap: space.xs,
    overflow: 'hidden',
    ...shadow,
  },
  glow: {
    position: 'absolute',
    right: -60,
    top: -60,
    width: 200,
    height: 200,
    borderRadius: 100,
    backgroundColor: 'rgba(94,224,176,0.12)',
  },
  summaryRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  plan: { padding: 0, overflow: 'hidden' },
  planArt: { height: 120, backgroundColor: colors.navySoft, justifyContent: 'flex-end' },
  planIcon: { position: 'absolute', right: space.lg, bottom: space.md },
  rate: {
    position: 'absolute',
    left: space.md,
    top: space.md,
    backgroundColor: colors.yieldBg,
    borderRadius: radius.pill,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  planBody: { padding: space.lg, gap: 4 },
  planFoot: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: space.xs },
  holdHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: space.sm },
});
