import Ionicons from '@expo/vector-icons/Ionicons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { router, useLocalSearchParams } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';

import { newIdempotencyKey } from '@/api/client';
import { wallet } from '@/api/endpoints';
import { messageFor } from '@/api/errors';
import type { CardTopUp, Wallet } from '@/api/types';
import { AmountField } from '@/components/AmountField';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { CopyField } from '@/components/CopyField';
import { Screen } from '@/components/Screen';
import { Banner, CardSkeleton, ErrorState } from '@/components/States';
import { Text } from '@/components/Text';
import { naira } from '@/lib/format';
import { keys, useMe, useWallet } from '@/lib/queries';
import { colors, font, radius, space } from '@/theme/tokens';

const MIN = 100;
const QUICK = ['5000', '10000', '20000', '50000'];

/**
 * Bank transfer or debit card.
 *
 * Bank transfer has two models, chosen by the server (`funding_mode`):
 * - permanent_dva: the customer's own account number; any transfer credits the wallet.
 * - on_demand_dynamic (Zest): a one-off account per top-up, created by POST /wallet/fund.
 *
 * Card: Monnify's hosted card page opens in an in-app browser; the wallet is credited when
 * Monnify confirms (webhook, or our status check when the browser closes).
 */
export default function Fund() {
  const summary = useWallet();
  // Opened from a repayment or an investment with the shortfall pre-filled, or by the card
  // page's return link (`reference`).
  const params = useLocalSearchParams<{ amount?: string; reference?: string }>();
  const [amount, setAmount] = useState(() => (params.amount && /^\d+$/.test(params.amount) ? params.amount : ''));
  const [method, setMethod] = useState<'transfer' | 'card'>(params.reference ? 'card' : 'transfer');
  const switcher = <MethodSwitch value={method} onChange={setMethod} />;

  if (method === 'card') {
    return <CardTopUpFlow amount={amount} setAmount={setAmount} switcher={switcher} reference={params.reference} />;
  }

  if (summary.isPending) {
    return (
      <Screen edges={['bottom']}>
        <CardSkeleton />
      </Screen>
    );
  }
  if (summary.isError || !summary.data) {
    return (
      <Screen edges={['bottom']}>
        <ErrorState error={summary.error} onRetry={() => summary.refetch()} />
      </Screen>
    );
  }
  return summary.data.funding_mode === 'on_demand_dynamic' ? (
    <OnDemand amount={amount} setAmount={setAmount} switcher={switcher} />
  ) : (
    <PermanentAccount w={summary.data} amount={amount} switcher={switcher} />
  );
}

function MethodSwitch({ value, onChange }: { value: 'transfer' | 'card'; onChange: (v: 'transfer' | 'card') => void }) {
  const options = [
    { id: 'transfer' as const, label: 'Bank transfer', icon: 'business-outline' as const },
    { id: 'card' as const, label: 'Debit card', icon: 'card-outline' as const },
  ];
  return (
    <View style={styles.switch} accessibilityRole="tablist">
      {options.map((o) => {
        const on = o.id === value;
        return (
          <Pressable
            key={o.id}
            accessibilityRole="tab"
            accessibilityState={{ selected: on }}
            onPress={() => onChange(o.id)}
            style={[styles.switchItem, on && styles.switchOn]}>
            <Ionicons name={o.icon} size={16} color={on ? colors.navy : colors.slate} />
            <Text variant="small" color={on ? colors.navy : colors.slate} style={{ fontFamily: font.semibold }}>
              {o.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const POLL_MS = 2500;
const POLL_TRIES = 8;

function CardTopUpFlow({
  amount,
  setAmount,
  switcher,
  reference,
}: {
  amount: string;
  setAmount: (v: string) => void;
  switcher: ReactNode;
  reference?: string;
}) {
  const queryClient = useQueryClient();
  const key = useRef(newIdempotencyKey());
  const value = Number(amount || 0);
  const tooSmall = amount !== '' && value < MIN;
  const [started, setStarted] = useState<CardTopUp | null>(null);
  // Set once the card page has closed (or the app was opened by its return link).
  const [paidRef, setPaidRef] = useState<string | null>(reference ?? null);

  const choose = (v: string) => {
    setAmount(v);
    key.current = newIdempotencyKey();
  };

  // Ask the server until Monnify confirms (or says no); it checks with Monnify each time.
  const status = useQuery({
    queryKey: ['card-topup', paidRef],
    queryFn: () => wallet.cardTopUp(paidRef!),
    enabled: !!paidRef,
    refetchInterval: (q) =>
      q.state.data?.status === 'pending' && q.state.dataUpdateCount < POLL_TRIES ? POLL_MS : false,
  });
  const result = status.data ?? started;
  const polls = queryClient.getQueryState(['card-topup', paidRef])?.dataUpdateCount ?? 0;
  const checking = !!paidRef && (status.isPending || (result?.status === 'pending' && polls < POLL_TRIES));

  useEffect(() => {
    if (result?.status !== 'completed') return;
    queryClient.invalidateQueries({ queryKey: keys.wallet });
    queryClient.invalidateQueries({ queryKey: keys.transactions });
  }, [result?.status, queryClient]);

  const start = useMutation({
    mutationFn: () => wallet.fundCard(Number(amount).toFixed(2), key.current),
    onSuccess: async (begun) => {
      setStarted(begun);
      if (begun.status !== 'pending' || !begun.checkout_url) return; // credited at once (demo server)
      await WebBrowser.openAuthSessionAsync(begun.checkout_url, 'ghtrust://fund').catch(() => undefined);
      setPaidRef(begun.reference);
    },
  });
  const check = () => status.refetch();

  if (result && result.status === 'completed') {
    return (
      <Screen edges={['bottom']} scroll={false} footer={<Button title="Done" onPress={() => router.back()} />}>
        <View style={styles.center}>
          <View style={[styles.badge, { backgroundColor: colors.yield }]}>
            <Ionicons name="checkmark" size={36} color={colors.white} />
          </View>
          <Text variant="title" align="center">
            {naira(result.amount)} added
          </Text>
          <Text muted align="center">
            Your wallet has been topped up by card.
          </Text>
        </View>
      </Screen>
    );
  }

  if (result && (checking || result.status === 'pending')) {
    return (
      <Screen
        edges={['bottom']}
        scroll={false}
        footer={
          checking ? null : (
            <>
              <Button title="Check again" onPress={check} />
              <Button title="Close" variant="ghost" onPress={() => router.back()} />
            </>
          )
        }>
        <View style={styles.center}>
          <View style={[styles.badge, { backgroundColor: colors.pendingBg }]}>
            {checking ? (
              <ActivityIndicator color={colors.pending} />
            ) : (
              <Ionicons name="time-outline" size={34} color={colors.pending} />
            )}
          </View>
          <Text variant="title" align="center">
            {checking ? 'Confirming your payment' : 'Waiting for your bank'}
          </Text>
          <Text muted align="center">
            {checking
              ? 'This takes a few seconds.'
              : "We haven't had confirmation yet. If you paid, your wallet is credited as soon as it arrives. You can close this screen."}
          </Text>
        </View>
      </Screen>
    );
  }

  return (
    <Screen
      edges={['bottom']}
      footer={
        <Button
          title={value > 0 ? `Pay ${naira(value)} by card` : 'Continue'}
          icon="card-outline"
          disabled={!amount || tooSmall}
          loading={start.isPending}
          onPress={() => start.mutate()}
        />
      }>
      {switcher}
      {result?.status === 'failed' ? <Banner message="The card payment didn't go through. You weren't charged." /> : null}
      {start.error ? <Banner message={messageFor(start.error)} /> : null}
      <AmountField
        label="How much do you want to add?"
        value={amount}
        onChange={choose}
        error={tooSmall ? `The minimum is ${naira(MIN)}.` : null}
        autoFocus
      />
      <View style={{ flexDirection: 'row', gap: space.xs, flexWrap: 'wrap' }}>
        {QUICK.map((q) => (
          <Button key={q} title={naira(q)} size="sm" variant="secondary" onPress={() => choose(q)} />
        ))}
      </View>
      <Text variant="small" muted>
        You'll enter your card details on our payment partner's secure page. We never see or store your card number.
      </Text>
    </Screen>
  );
}

function Done() {
  const queryClient = useQueryClient();
  return (
    <Button
      title="I've sent the money"
      onPress={() => {
        queryClient.invalidateQueries({ queryKey: keys.wallet });
        router.back();
      }}
    />
  );
}

function PermanentAccount({ w, amount, switcher }: { w: Wallet; amount: string; switcher: ReactNode }) {
  const me = useMe();
  if (!w.dva_account_number || w.dva_status !== 'active') {
    return (
      <Screen edges={['bottom']}>
        {switcher}
        <Banner
          tone="warning"
          message="Your GH Trust account number isn't ready yet. Please try again shortly, or contact your branch."
        />
      </Screen>
    );
  }
  return (
    <Screen edges={['bottom']} footer={<Done />}>
      {switcher}
      <Text variant="title">{amount ? `Transfer ${naira(amount)}` : 'Transfer from any bank'}</Text>
      <Text muted>
        Send money from your bank app to your GH Trust account below. Your wallet is credited automatically when it
        arrives, usually within minutes.
      </Text>
      <Card style={{ paddingVertical: space.xs }}>
        <CopyField label="Account number" value={w.dva_account_number} />
        <CopyField label="Bank" value={w.dva_bank_name ?? 'GH Trust'} last={!me.data} />
        {me.data ? <CopyField label="Account name" value={me.data.full_name} last /> : null}
      </Card>
      <Banner tone="info" message="This account number is yours to keep. Save it as a beneficiary in your bank app." />
    </Screen>
  );
}

function OnDemand({ amount, setAmount, switcher }: { amount: string; setAmount: (v: string) => void; switcher: ReactNode }) {
  const key = useRef(newIdempotencyKey());
  const value = Number(amount || 0);
  const tooSmall = amount !== '' && value < MIN;
  const fund = useMutation({ mutationFn: () => wallet.fund(amount, key.current) });
  const choose = (v: string) => {
    setAmount(v);
    key.current = newIdempotencyKey(); // a different amount is a different action
  };

  const session = fund.data;
  if (session) {
    return (
      <Screen edges={['bottom']} footer={<Done />}>
        <Text variant="title">Transfer {naira(session.amount)}</Text>
        <Text muted>
          From your bank app, send exactly this amount to the account below. Your wallet is credited as soon as it
          arrives.
        </Text>
        <Card style={{ paddingVertical: space.xs }}>
          <CopyField label="Account number" value={session.account_number} />
          <CopyField label="Bank" value={session.bank_name} />
          <CopyField label="Account name" value={session.account_name} />
          <CopyField label="Amount" value={String(session.amount)} last />
        </Card>
        <Banner tone="info" message={`This account is valid for ${session.expires_in_minutes} minutes.`} />
      </Screen>
    );
  }

  return (
    <Screen
      edges={['bottom']}
      footer={<Button title="Continue" disabled={!amount || tooSmall} loading={fund.isPending} onPress={() => fund.mutate()} />}>
      {switcher}
      {fund.error ? <Banner message={messageFor(fund.error)} /> : null}
      <AmountField
        label="How much do you want to add?"
        value={amount}
        onChange={choose}
        error={tooSmall ? `The minimum is ${naira(MIN)}.` : null}
        autoFocus
      />
      <View style={{ flexDirection: 'row', gap: space.xs, flexWrap: 'wrap' }}>
        {QUICK.map((q) => (
          <Button key={q} title={naira(q)} size="sm" variant="secondary" onPress={() => choose(q)} />
        ))}
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  switch: {
    flexDirection: 'row',
    backgroundColor: colors.slateFill,
    borderRadius: radius.md,
    padding: 4,
    gap: 4,
  },
  switchItem: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    minHeight: 40,
    borderRadius: radius.sm,
  },
  switchOn: { backgroundColor: colors.card },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: space.sm },
  badge: {
    width: 84,
    height: 84,
    borderRadius: 42,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: space.md,
  },
});
