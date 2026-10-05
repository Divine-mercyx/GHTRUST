import Ionicons from '@expo/vector-icons/Ionicons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import * as Haptics from 'expo-haptics';
import { Image } from 'expo-image';
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { Platform, StyleSheet, View } from 'react-native';
import Animated, { ZoomIn } from 'react-native-reanimated';

import { newIdempotencyKey } from '@/api/client';
import { investments } from '@/api/endpoints';
import { ApiError, messageFor } from '@/api/errors';
import { AmountField } from '@/components/AmountField';
import { Badge } from '@/components/Badge';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { Banner, CardSkeleton, EmptyState } from '@/components/States';
import { Text } from '@/components/Text';
import { TransactionPinSheet } from '@/components/TransactionPinSheet';
import { date, naira } from '@/lib/format';
import { investAmountError, maturityFrom, planImage, projectedReturn, RISK } from '@/lib/investments';
import { keys, useFeatures, useInvestmentPlans, useWallet } from '@/lib/queries';
import { colors, font, radius, space } from '@/theme/tokens';

/** One plan: what it pays, a live calculation, and investing from the wallet with the PIN. */
export default function InvestPlan() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const queryClient = useQueryClient();
  const { investments: open, wallet: walletOn } = useFeatures();
  const plans = useInvestmentPlans();
  const summary = useWallet();
  const plan = plans.data?.find((p) => p.id === id);
  const [amount, setAmount] = useState('');
  const [askPin, setAskPin] = useState(false);
  const key = useRef(newIdempotencyKey());

  const invest = useMutation({
    mutationFn: (pin: string) => investments.invest(id, Number(amount).toFixed(2), pin, key.current),
    onSuccess: () => {
      if (Platform.OS !== 'web')
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: keys.wallet });
      queryClient.invalidateQueries({ queryKey: keys.transactions });
      queryClient.invalidateQueries({ queryKey: keys.investments });
    },
  });

  useEffect(() => {
    if (!invest.isPending) key.current = newIdempotencyKey();
  }, [amount]); // eslint-disable-line react-hooks/exhaustive-deps

  if (invest.isSuccess) {
    const inv = invest.data;
    return (
      <Screen edges={['bottom']} scroll={false} footer={<Button title="Done" onPress={() => router.back()} />}>
        <View style={styles.success}>
          <Animated.View entering={ZoomIn.springify()} style={styles.tick}>
            <Ionicons name="trending-up" size={38} color={colors.white} />
          </Animated.View>
          <Text variant="title" align="center">
            You've invested {naira(inv.amount)}
          </Text>
          <Text muted align="center">
            {naira(inv.maturity_value)} comes back to your wallet on {date(inv.maturity_date)}.
          </Text>
          <View style={styles.earn}>
            <Text variant="bodyStrong" color={colors.yield}>
              +{naira(inv.projected_return)} returns
            </Text>
          </View>
          <Text variant="small" muted align="center">
            Reference {inv.reference}
          </Text>
        </View>
      </Screen>
    );
  }

  if (plans.isPending) {
    return (
      <Screen edges={['bottom']}>
        <CardSkeleton lines={5} />
      </Screen>
    );
  }
  if (!plan) {
    return (
      <Screen edges={['bottom']}>
        <EmptyState icon="leaf-outline" title="Plan not available" body="This plan is no longer on offer." />
      </Screen>
    );
  }

  const value = Number(amount || 0);
  const rate = Number(plan.return_rate);
  const returns = value > 0 ? projectedReturn(value, rate, plan.tenure_months) : 0;
  const balance = summary.data?.available_balance ?? 0;
  const shortfall = value > balance ? Math.ceil(value - balance) : 0;
  const amountError = investAmountError(amount, plan);
  const risk = RISK[plan.risk] ?? RISK.low;
  const image = planImage(plan);
  const pinError = invest.error instanceof ApiError && invest.error.code.startsWith('TRANSACTION_PIN_');
  const quick = [Number(plan.min_amount), Number(plan.min_amount) * 2, Number(plan.min_amount) * 5].filter(
    (q) => !plan.max_amount || q <= Number(plan.max_amount),
  );

  return (
    <Screen
      edges={['bottom']}
      footer={
        !open ? (
          <Button title="Investing opens soon" disabled />
        ) : shortfall > 0 && !amountError ? (
          <Button
            title={`Add ${naira(shortfall)} to your wallet`}
            icon="add"
            disabled={!walletOn}
            onPress={() => router.push({ pathname: '/fund', params: { amount: String(shortfall) } })}
          />
        ) : (
          <Button
            title={value > 0 ? `Invest ${naira(value)}` : 'Invest'}
            disabled={!value || !!amountError}
            loading={invest.isPending}
            onPress={() => {
              invest.reset();
              setAskPin(true);
            }}
          />
        )
      }>
      <TransactionPinSheet
        visible={askPin}
        summary={`Invest ${naira(value)} in ${plan.name}`}
        onClose={() => setAskPin(false)}
        onPin={(pin) => invest.mutateAsync(pin)}
      />

      <View style={styles.hero}>
        {image ? <Image source={{ uri: image }} style={StyleSheet.absoluteFill} contentFit="cover" /> : null}
        <View style={styles.heroShade} />
        <View style={styles.rate}>
          <Text variant="bodyStrong" color={colors.yield}>
            {rate}% a year
          </Text>
        </View>
        <Text variant="title" color={colors.white}>
          {plan.name}
        </Text>
      </View>

      {plan.description ? <Text muted>{plan.description}</Text> : null}

      <Card style={{ paddingVertical: space.xs }}>
        <Fact label="Yearly return" value={`${rate}%`} accent />
        <Fact label="Term" value={`${plan.tenure_months} months`} />
        <Fact
          label="Amount"
          value={plan.max_amount ? `${naira(plan.min_amount)} – ${naira(plan.max_amount)}` : `From ${naira(plan.min_amount)}`}
        />
        <View style={styles.fact}>
          <Text variant="small" muted>
            Risk
          </Text>
          <Badge label={risk.label} tone={risk.tone} />
        </View>
      </Card>

      {invest.error && !pinError ? (
        <Banner
          message={
            invest.error instanceof ApiError && invest.error.code === 'INSUFFICIENT_FUNDS'
              ? 'Your wallet balance changed. Check the amount and try again.'
              : messageFor(invest.error)
          }
        />
      ) : null}

      <AmountField label="How much do you want to invest?" value={amount} onChange={setAmount} error={amountError} />
      <View style={styles.quick}>
        {quick.map((q) => (
          <Button key={q} title={naira(q)} size="sm" variant="secondary" onPress={() => setAmount(String(q))} />
        ))}
      </View>

      <View style={styles.calc}>
        <View style={styles.calcRow}>
          <Text variant="small" color={colors.slate}>
            Returns
          </Text>
          <Text variant="bodyStrong" color={colors.yield}>
            +{naira(returns, { kobo: true })}
          </Text>
        </View>
        <View style={styles.calcRow}>
          <Text variant="small" color={colors.slate}>
            Paid into your wallet on {date(maturityFrom(plan.tenure_months).toISOString())}
          </Text>
          <Text variant="bodyStrong" style={{ fontFamily: font.bold }}>
            {naira(value + returns, { kobo: true })}
          </Text>
        </View>
      </View>

      <View style={styles.calcRow}>
        <Text variant="small" muted>
          Wallet balance
        </Text>
        <Text variant="small" style={{ fontFamily: font.semibold }} color={shortfall > 0 ? colors.pending : colors.text}>
          {naira(balance, { kobo: true })}
        </Text>
      </View>
      {shortfall > 0 && !amountError ? (
        <Banner tone="warning" message={`Add ${naira(shortfall)} to your wallet first, by bank transfer or card.`} />
      ) : null}
      <Text variant="small" muted>
        Your money is locked until the plan matures. The rate you see now is fixed for this investment.
      </Text>
    </Screen>
  );
}

function Fact({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <View style={styles.fact}>
      <Text variant="small" muted>
        {label}
      </Text>
      <Text variant="bodyStrong" color={accent ? colors.yield : colors.text}>
        {value}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  hero: {
    height: 160,
    borderRadius: radius.lg,
    overflow: 'hidden',
    backgroundColor: colors.navy,
    justifyContent: 'flex-end',
    padding: space.lg,
  },
  heroShade: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, backgroundColor: 'rgba(15,26,60,0.35)' },
  rate: {
    position: 'absolute',
    top: space.md,
    left: space.md,
    backgroundColor: colors.yieldBg,
    borderRadius: radius.pill,
    paddingHorizontal: 12,
    paddingVertical: 4,
  },
  fact: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: space.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  quick: { flexDirection: 'row', gap: space.xs, flexWrap: 'wrap' },
  calc: { backgroundColor: colors.slateFill, borderRadius: radius.md, padding: space.md, gap: space.xs },
  calcRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: space.sm },
  success: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: space.sm },
  tick: {
    width: 84,
    height: 84,
    borderRadius: 42,
    backgroundColor: colors.yield,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: space.md,
  },
  earn: { backgroundColor: colors.yieldBg, borderRadius: radius.pill, paddingHorizontal: 14, paddingVertical: 6 },
});
