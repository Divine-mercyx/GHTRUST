import { router } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import { Button } from '@/components/Button';
import { Card, SectionHeader } from '@/components/Card';
import { CopyField } from '@/components/CopyField';
import { Screen } from '@/components/Screen';
import { Banner, CardSkeleton, ErrorState } from '@/components/States';
import { Text } from '@/components/Text';
import { naira } from '@/lib/format';
import { useWallet } from '@/lib/queries';
import { colors, radius, space } from '@/theme/tokens';

export default function WalletTab() {
  const wallet = useWallet();
  const w = wallet.data;

  return (
    <Screen onRefresh={() => wallet.refetch()} refreshing={wallet.isRefetching}>
      <Text variant="title">Wallet</Text>

      {wallet.isPending ? (
        <CardSkeleton lines={2} />
      ) : wallet.isError || !w ? (
        <ErrorState error={wallet.error} onRetry={() => wallet.refetch()} />
      ) : (
        <>
          <View style={styles.balance}>
            <Text variant="caption" color={colors.cyan}>
              AVAILABLE BALANCE
            </Text>
            <Text variant="display" color={colors.white}>
              {naira(w.available_balance, { kobo: true })}
            </Text>
            {w.locked_balance > 0 ? (
              <Text variant="small" color="rgba(255,255,255,0.75)">
                {naira(w.locked_balance)} held for pending transactions
              </Text>
            ) : null}
            <Button
              title="Add money"
              icon="add"
              onPress={() => router.push('/fund')}
              style={{ backgroundColor: colors.cyan, borderColor: colors.cyan, marginTop: space.lg }}
            />
          </View>

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
            <Banner tone="warning" message="We couldn't set up your account number yet. Use Add money to fund by transfer." />
          ) : null}

          <SectionHeader title="How repayments work" />
          <Card>
            <Text variant="small" muted>
              Loan repayments are taken from your wallet balance. Add money before your due date, then tap Repay on
              your loan.
            </Text>
          </Card>
        </>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  balance: { backgroundColor: colors.navy, borderRadius: radius.xl, padding: space.xl, gap: 4 },
});
