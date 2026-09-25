import { useMutation, useQueryClient } from '@tanstack/react-query';
import { router, useLocalSearchParams } from 'expo-router';
import { useRef, useState } from 'react';
import { View } from 'react-native';

import { newIdempotencyKey } from '@/api/client';
import { wallet } from '@/api/endpoints';
import { messageFor } from '@/api/errors';
import type { Wallet } from '@/api/types';
import { AmountField } from '@/components/AmountField';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { CopyField } from '@/components/CopyField';
import { Screen } from '@/components/Screen';
import { Banner, CardSkeleton, ErrorState } from '@/components/States';
import { Text } from '@/components/Text';
import { naira } from '@/lib/format';
import { keys, useMe, useWallet } from '@/lib/queries';
import { space } from '@/theme/tokens';

const MIN = 100;
const QUICK = ['5000', '10000', '20000', '50000'];

/**
 * Two funding models, chosen by the server (`funding_mode`):
 * - permanent_dva: the customer's own account number; any transfer credits the wallet.
 * - on_demand_dynamic (Zest): a one-off account per top-up, created by POST /wallet/fund.
 */
export default function Fund() {
  const summary = useWallet();
  // Opened from a repayment with the shortfall pre-filled.
  const params = useLocalSearchParams<{ amount?: string }>();
  const [amount, setAmount] = useState(() => (params.amount && /^\d+$/.test(params.amount) ? params.amount : ''));

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
    <OnDemand amount={amount} setAmount={setAmount} />
  ) : (
    <PermanentAccount w={summary.data} amount={amount} />
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

function PermanentAccount({ w, amount }: { w: Wallet; amount: string }) {
  const me = useMe();
  if (!w.dva_account_number || w.dva_status !== 'active') {
    return (
      <Screen edges={['bottom']}>
        <Banner
          tone="warning"
          message="Your GH Trust account number isn't ready yet. Please try again shortly, or contact your branch."
        />
      </Screen>
    );
  }
  return (
    <Screen edges={['bottom']} footer={<Done />}>
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

function OnDemand({ amount, setAmount }: { amount: string; setAmount: (v: string) => void }) {
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
