import Ionicons from '@expo/vector-icons/Ionicons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import * as Haptics from 'expo-haptics';
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { Platform, Pressable, StyleSheet, View } from 'react-native';
import Animated, { ZoomIn } from 'react-native-reanimated';

import { newIdempotencyKey } from '@/api/client';
import { loans } from '@/api/endpoints';
import { ApiError, messageFor } from '@/api/errors';
import { AmountField } from '@/components/AmountField';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { Banner, CardSkeleton, ErrorState } from '@/components/States';
import { Text } from '@/components/Text';
import { naira } from '@/lib/format';
import { nextInstallment } from '@/lib/loans';
import { keys, useLoan, useWallet } from '@/lib/queries';
import { colors, font, radius, space } from '@/theme/tokens';

type Choice = 'next' | 'all' | 'custom';

export default function Repay() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const queryClient = useQueryClient();
  const loan = useLoan(id);
  const wallet = useWallet();
  const [choice, setChoice] = useState<Choice>('next');
  const [custom, setCustom] = useState('');
  // One key per payment attempt: retries after a timeout replay, never double-charge.
  const key = useRef(newIdempotencyKey());

  const l = loan.data;
  const next = l ? nextInstallment(l.schedule) : undefined;
  const amount =
    choice === 'next' ? (next?.amount_due ?? '0') : choice === 'all' ? (l?.outstanding ?? '0') : custom || '0';
  const value = Number(amount);
  const balance = wallet.data?.available_balance ?? 0;
  const outstanding = Number(l?.outstanding ?? 0);

  let error: string | null = null;
  if (choice === 'custom' && custom && value <= 0) error = 'Enter an amount.';
  else if (value > outstanding) error = `You only owe ${naira(outstanding)}.`;

  const pay = useMutation({
    mutationFn: () => loans.repay(id, value.toFixed(2), key.current),
    onSuccess: () => {
      if (Platform.OS !== 'web') Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: keys.loans });
      queryClient.invalidateQueries({ queryKey: keys.wallet });
    },
  });

  // Changing the amount is a new action → new key.
  useEffect(() => {
    if (!pay.isPending) key.current = newIdempotencyKey();
  }, [choice, custom]); // eslint-disable-line react-hooks/exhaustive-deps

  if (pay.isSuccess) {
    return (
      <Screen edges={['bottom']} scroll={false} footer={<Button title="Done" onPress={() => router.back()} />}>
        <View style={styles.success}>
          <Animated.View entering={ZoomIn.springify()} style={styles.tick}>
            <Ionicons name="checkmark" size={40} color={colors.white} />
          </Animated.View>
          <Text variant="title" align="center">
            Payment received
          </Text>
          <Text muted align="center">
            {naira(pay.data.amount)} was applied to your loan. Your updated schedule is on the loan page.
          </Text>
        </View>
      </Screen>
    );
  }

  if (loan.isPending) {
    return (
      <Screen edges={['bottom']}>
        <CardSkeleton />
      </Screen>
    );
  }
  if (loan.isError || !l) {
    return (
      <Screen edges={['bottom']}>
        <ErrorState error={loan.error} onRetry={() => loan.refetch()} />
      </Screen>
    );
  }

  const short = wallet.data && value > balance;
  const insufficient = pay.error instanceof ApiError && pay.error.code === 'INSUFFICIENT_FUNDS';

  return (
    <Screen
      edges={['bottom']}
      footer={
        short ? (
          <Button
            title={`Add ${naira(Math.ceil(value - balance))} to wallet`}
            icon="add"
            onPress={() => router.push({ pathname: '/fund', params: { amount: String(Math.ceil(value - balance)) } })}
          />
        ) : (
          <Button
            title={value > 0 ? `Pay ${naira(value)}` : 'Pay'}
            disabled={!!error || value <= 0}
            loading={pay.isPending}
            onPress={() => pay.mutate()}
          />
        )
      }>
      {pay.error && !insufficient ? <Banner message={messageFor(pay.error)} /> : null}

      <View style={{ gap: space.sm }}>
        {next ? (
          <Option
            selected={choice === 'next'}
            onPress={() => setChoice('next')}
            title={next.status === 'overdue' ? 'Overdue payment' : 'Next payment'}
            value={naira(next.amount_due)}
          />
        ) : null}
        <Option selected={choice === 'all'} onPress={() => setChoice('all')} title="Pay off the loan" value={naira(l.outstanding)} />
        <Option selected={choice === 'custom'} onPress={() => setChoice('custom')} title="Another amount" value="" />
      </View>

      {choice === 'custom' ? (
        <AmountField label="Amount" value={custom} onChange={setCustom} error={error} autoFocus />
      ) : error ? (
        <Banner message={error} />
      ) : null}

      <Card style={styles.balance}>
        <Ionicons name="wallet-outline" size={20} color={colors.cyanDeep} />
        <Text variant="small" muted style={{ flex: 1 }}>
          Paid from your wallet
        </Text>
        <Text variant="bodyStrong" color={short || insufficient ? colors.error : colors.text}>
          {wallet.data ? naira(balance, { kobo: true }) : '—'}
        </Text>
      </Card>
      {short || insufficient ? (
        <Banner tone="warning" message="Your wallet balance isn't enough for this payment. Add money first, then come back." />
      ) : null}
      <Text variant="small" muted>
        Payments go to your oldest unpaid installment first, interest before principal.
      </Text>
    </Screen>
  );
}

function Option({ selected, onPress, title, value }: { selected: boolean; onPress: () => void; title: string; value: string }) {
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityState={{ checked: selected }}
      accessibilityLabel={`${title} ${value}`}
      onPress={onPress}
      style={[styles.option, selected && styles.optionOn]}>
      <View style={[styles.radio, selected && styles.radioOn]}>{selected ? <View style={styles.radioDot} /> : null}</View>
      <Text variant="bodyStrong" style={{ flex: 1 }}>
        {title}
      </Text>
      <Text variant="bodyStrong" style={{ fontFamily: font.bold }}>
        {value}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  option: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
    padding: space.md,
    minHeight: 60,
    borderRadius: radius.lg,
    borderWidth: 1.5,
    borderColor: colors.border,
    backgroundColor: colors.card,
  },
  optionOn: { borderColor: colors.navy, backgroundColor: '#F7F9FD' },
  radio: { width: 22, height: 22, borderRadius: 11, borderWidth: 2, borderColor: colors.borderStrong, alignItems: 'center', justifyContent: 'center' },
  radioOn: { borderColor: colors.navy },
  radioDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: colors.navy },
  balance: { flexDirection: 'row', alignItems: 'center', gap: space.sm, paddingVertical: space.md },
  success: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: space.sm },
  tick: {
    width: 84,
    height: 84,
    borderRadius: 42,
    backgroundColor: colors.success,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: space.md,
  },
});
