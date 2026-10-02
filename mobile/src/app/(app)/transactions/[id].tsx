import Ionicons from '@expo/vector-icons/Ionicons';
import { router, useLocalSearchParams } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import { Badge, toneColor } from '@/components/Badge';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { CopyField } from '@/components/CopyField';
import { Screen } from '@/components/Screen';
import { Banner, CardSkeleton, ErrorState } from '@/components/States';
import { Text } from '@/components/Text';
import { transactionDetail, transactionIcon, transactionStatus } from '@/lib/activity';
import { dateTime, naira } from '@/lib/format';
import { useTransaction } from '@/lib/queries';
import { colors, radius, space } from '@/theme/tokens';

const KIND: Record<string, string> = {
  funding: 'Money added to wallet',
  loan_payout: 'Loan paid into wallet',
  repayment: 'Loan repayment from wallet',
  withdrawal: 'Withdrawal to bank',
};

/** Receipt for one wallet transaction. */
export default function TransactionReceipt() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const tx = useTransaction(id);
  const t = tx.data;

  if (tx.isPending) {
    return (
      <Screen edges={['bottom']}>
        <CardSkeleton lines={5} />
      </Screen>
    );
  }
  if (tx.isError || !t) {
    return (
      <Screen edges={['bottom']}>
        <ErrorState error={tx.error} onRetry={() => tx.refetch()} />
      </Screen>
    );
  }

  const status = transactionStatus(t.status);
  const tint = toneColor(status.tone);
  const sign = t.direction === 'in' ? '+' : t.status === 'failed' ? '' : '−';

  return (
    <Screen
      edges={['bottom']}
      onRefresh={() => tx.refetch()}
      refreshing={tx.isRefetching}
      footer={
        <>
          {t.loan_id ? (
            <Button
              title="View loan"
              variant="secondary"
              icon="document-text-outline"
              onPress={() => router.push(`/loans/${t.loan_id}`)}
            />
          ) : null}
          <Button
            title="Report a problem"
            variant="ghost"
            onPress={() =>
              router.push({
                pathname: '/support/new',
                params: { category: 'payments', related_type: 'transaction', related_id: t.id },
              })
            }
          />
        </>
      }>
      <View style={styles.head}>
        <View style={[styles.icon, { backgroundColor: `${tint}18` }]}>
          <Ionicons name={transactionIcon(t.kind)} size={28} color={tint} />
        </View>
        <Text variant="small" muted>
          {t.title}
        </Text>
        <Text
          variant="display"
          color={t.direction === 'in' ? colors.success : colors.text}
          style={t.status === 'failed' ? styles.struck : undefined}>
          {sign}
          {naira(t.amount, { kobo: true })}
        </Text>
        <View style={{ alignItems: 'center' }}>
          <Badge label={status.label} tone={status.tone} />
        </View>
      </View>

      {t.note ? <Banner tone={t.status === 'failed' ? 'warning' : 'info'} message={t.note} /> : null}

      <Card style={{ paddingVertical: space.xs }}>
        <Line label="Type" value={KIND[t.kind] ?? t.title} />
        {transactionDetail(t) ? (
          <Line
            label={t.kind === 'withdrawal' ? 'To' : t.kind === 'repayment' || t.kind === 'loan_payout' ? 'Loan' : 'From'}
            value={transactionDetail(t)}
          />
        ) : null}
        <Line label="Date" value={dateTime(t.created_at)} />
        {t.completed_at && t.status === 'completed' && t.kind === 'withdrawal' ? (
          <Line label="Completed" value={dateTime(t.completed_at)} />
        ) : null}
        {t.reference ? <CopyField label="Reference" value={t.reference} last /> : null}
      </Card>
      <Text variant="small" muted style={{ paddingHorizontal: space.xs }}>
        Quote the reference if you contact GH Trust about this transaction.
      </Text>
    </Screen>
  );
}

function Line({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.line}>
      <Text variant="small" muted>
        {label}
      </Text>
      <Text variant="bodyStrong" style={styles.value} numberOfLines={2}>
        {value}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  head: { alignItems: 'center', gap: space.xs, paddingVertical: space.md },
  icon: {
    width: 64,
    height: 64,
    borderRadius: radius.lg,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: space.xs,
  },
  struck: { textDecorationLine: 'line-through', color: colors.textMuted },
  line: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: space.md,
    paddingVertical: space.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  value: { flexShrink: 1, textAlign: 'right' },
});
