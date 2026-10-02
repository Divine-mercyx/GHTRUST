import { router } from 'expo-router';
import { useMemo } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { Button } from '@/components/Button';
import { Card, Row, SectionHeader } from '@/components/Card';
import { CopyField } from '@/components/CopyField';
import { TransactionItem } from '@/components/home/TransactionItem';
import { Screen } from '@/components/Screen';
import { Banner, CardSkeleton, ErrorState } from '@/components/States';
import { Text } from '@/components/Text';
import { fromTransaction, shortAccount } from '@/lib/activity';
import { naira } from '@/lib/format';
import { useApplications, useTransactions, useWallet } from '@/lib/queries';
import { applicationStatus } from '@/lib/status';
import { colors, font, radius, shadow, space } from '@/theme/tokens';

const RECENT = 4;
// Approved but not paid out yet: the money is coming to the wallet.
const PAYING_OUT = new Set(['approved', 'offer_sent', 'offer_accepted', 'product_gate_pending', 'processing_fee_paid', 'ready_to_disburse']);

export default function WalletTab() {
  const wallet = useWallet();
  const history = useTransactions();
  const applications = useApplications();
  const incoming = (applications.data?.items ?? []).filter((a) => PAYING_OUT.has(a.status));
  const w = wallet.data;
  const recent = useMemo(
    () => (history.data?.pages[0]?.items ?? []).slice(0, RECENT).map(fromTransaction),
    [history.data],
  );

  return (
    <Screen
      onRefresh={() => {
        wallet.refetch();
        history.refetch();
      }}
      refreshing={wallet.isRefetching}>
      <Text variant="title">Wallet</Text>

      {wallet.isPending ? (
        <CardSkeleton lines={2} />
      ) : wallet.isError || !w ? (
        <ErrorState error={wallet.error} onRetry={() => wallet.refetch()} />
      ) : (
        <>
          <View style={styles.balance}>
            <View pointerEvents="none" style={styles.glow} />
            <Text variant="caption" color={colors.cyan}>
              AVAILABLE BALANCE
            </Text>
            <Text variant="display" color={colors.white}>
              {naira(w.available_balance, { kobo: true })}
            </Text>
            {w.locked_balance > 0 ? (
              <Text variant="small" color="rgba(255,255,255,0.75)">
                {naira(w.locked_balance)} on its way to your bank
              </Text>
            ) : null}
            <View style={styles.actions}>
              <Button
                title="Add money"
                icon="add"
                onPress={() => router.push('/fund')}
                style={styles.addMoney}
              />
              <Button
                title="Withdraw"
                icon="arrow-up"
                onPress={() => router.push('/withdraw')}
                style={styles.withdraw}
              />
            </View>
          </View>

          {incoming.length > 0 ? (
            <>
              <SectionHeader title="Coming to your wallet" />
              <Card style={{ paddingVertical: space.xs }}>
                {incoming.map((a, i) => (
                  <Row
                    key={a.id}
                    icon="time-outline"
                    title={`${naira(a.approved_amount ?? a.requested_amount)} · ${a.product_name}`}
                    subtitle={`${applicationStatus(a.status).label}. Paid into your wallet once it's sent.`}
                    onPress={() => router.push(`/applications/${a.id}`)}
                    last={i === incoming.length - 1}
                  />
                ))}
              </Card>
            </>
          ) : null}

          <SectionHeader
            title="Recent transactions"
            action={
              recent.length > 0 ? (
                <Pressable accessibilityRole="button" hitSlop={10} onPress={() => router.push('/transactions')}>
                  <Text variant="small" color={colors.cyanDeep} style={{ fontFamily: font.semibold }}>
                    See all
                  </Text>
                </Pressable>
              ) : undefined
            }
          />
          {history.isPending ? (
            <CardSkeleton lines={2} />
          ) : history.isError ? (
            <ErrorState error={history.error} onRetry={() => history.refetch()} />
          ) : recent.length === 0 ? (
            <Card>
              <Text variant="small" muted>
                No transactions yet. Loans paid to you, money you add, repayments and withdrawals will show up here.
              </Text>
            </Card>
          ) : (
            <View style={styles.list}>
              {recent.map((item, i) => (
                <TransactionItem key={item.id} item={item} last={i === recent.length - 1} />
              ))}
            </View>
          )}

          <SectionHeader title="Withdrawals go to" />
          <Card style={{ paddingVertical: space.xs }}>
            {w.payout_account ? (
              <Row
                icon="business"
                title={w.payout_account.account_name ?? 'Your account'}
                subtitle={`${w.payout_account.bank_name ?? 'Bank'} · ${shortAccount(w.payout_account.account_number_masked)}`}
                onPress={() => router.push('/payout-account')}
                last
              />
            ) : (
              <Row
                icon="add-circle-outline"
                title="Add a bank account"
                subtitle="Needed before you can withdraw"
                onPress={() => router.push('/payout-account')}
                last
              />
            )}
          </Card>

          {w.dva_account_number ? (
            <>
              <SectionHeader title="Your GH Trust account" />
              <Card style={{ paddingVertical: space.xs }}>
                <CopyField label="Account number" value={w.dva_account_number} />
                <CopyField label="Bank" value={w.dva_bank_name ?? 'GH Trust'} last />
              </Card>
              <Text variant="small" muted style={{ paddingHorizontal: space.xs }}>
                Transfer to this account from any bank app and your wallet is credited automatically.
              </Text>
            </>
          ) : w.dva_status === 'failed' ? (
            <Banner
              tone="warning"
              message="We couldn't set up your account number yet. Use Add money to fund by transfer."
            />
          ) : null}
        </>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  balance: { backgroundColor: colors.navy, borderRadius: radius.xl - 4, padding: space.xl, gap: 4, overflow: 'hidden' },
  glow: {
    position: 'absolute',
    width: 220,
    height: 220,
    borderRadius: 110,
    top: -120,
    right: -80,
    backgroundColor: colors.cyan,
    opacity: 0.16,
  },
  actions: { flexDirection: 'row', gap: space.sm, marginTop: space.lg },
  addMoney: { flex: 1, paddingHorizontal: space.sm, backgroundColor: colors.cyan, borderColor: colors.cyan },
  withdraw: { flex: 1, paddingHorizontal: space.sm, backgroundColor: 'rgba(255,255,255,0.14)', borderColor: 'transparent' },
  list: { backgroundColor: colors.card, borderRadius: radius.lg, overflow: 'hidden', ...shadow },
});
