import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Linking, Pressable, StyleSheet, View } from 'react-native';

import { Badge } from '@/components/Badge';
import { Button } from '@/components/Button';
import { Card, Row, SectionHeader } from '@/components/Card';
import { productName } from '@/components/loans';
import { Screen } from '@/components/Screen';
import { CardSkeleton, ErrorState, ProgressBar } from '@/components/States';
import { Text } from '@/components/Text';
import { date, dateTime, humanize, naira, relativeDue } from '@/lib/format';
import { nextInstallment } from '@/lib/loans';
import { useFeatures, useLoan } from '@/lib/queries';
import { CADENCE, installmentStatus, loanStatus } from '@/lib/status';
import { colors, font, radius, space } from '@/theme/tokens';

export default function LoanDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const loan = useLoan(id);
  const { wallet, support } = useFeatures();
  const [showAll, setShowAll] = useState(false);
  const l = loan.data;

  if (loan.isPending) {
    return (
      <Screen edges={['bottom']}>
        <CardSkeleton lines={3} />
        <CardSkeleton lines={4} />
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

  const s = loanStatus(l.status);
  const open = l.status === 'active' || l.status === 'overdue';
  const next = nextInstallment(l.schedule);
  const schedule = showAll ? l.schedule : l.schedule.slice(0, 6);

  return (
    <Screen
      edges={['bottom']}
      onRefresh={() => loan.refetch()}
      refreshing={loan.isRefetching}
      footer={open && wallet ? <Button title="Make a repayment" icon="flash" onPress={() => router.push(`/repay/${l.id}`)} /> : null}>
      <Card>
        <View style={styles.between}>
          <Text variant="heading">{productName(l.product_type)}</Text>
          <Badge label={s.label} tone={s.tone} />
        </View>
        <Text variant="caption" muted style={{ marginTop: space.md }}>
          OUTSTANDING
        </Text>
        <Text variant="display">{naira(l.outstanding)}</Text>
        <View style={{ gap: 6, marginTop: space.sm }}>
          <ProgressBar
            value={Number(l.amount_paid) / (Number(l.total_repayable) || 1)}
            color={l.status === 'overdue' ? colors.error : colors.success}
          />
          <Text variant="small" muted>
            {naira(l.amount_paid)} of {naira(l.total_repayable)} repaid
          </Text>
        </View>
        {s.hint ? (
          <Text variant="small" color={l.status === 'overdue' ? colors.error : colors.textMuted} style={{ marginTop: space.sm }}>
            {s.hint}
          </Text>
        ) : null}
      </Card>

      {open && next ? (
        <Card style={[styles.next, next.status === 'overdue' && { borderColor: colors.error }]}>
          <View style={{ flex: 1 }}>
            <Text variant="caption" muted>
              {next.status === 'overdue' ? 'OVERDUE PAYMENT' : 'NEXT PAYMENT'}
            </Text>
            <Text variant="title">{naira(next.amount_due)}</Text>
            <Text variant="small" color={next.status === 'overdue' ? colors.error : colors.textMuted}>
              {date(next.due_date)} · {relativeDue(next.due_date)}
            </Text>
          </View>
          <Text variant="small" muted>
            {next.installment} of {l.installments_count}
          </Text>
        </Card>
      ) : null}

      {open && !wallet ? (
        <Card style={{ gap: space.xs }}>
          <Text variant="heading">How to repay</Text>
          <Text variant="small" muted>
            Pay at your branch or by transfer to GH Trust, quoting your name and loan. Your payment shows here once it's
            recorded.
          </Text>
          {support?.phone ? (
            <Button title={`Call ${support.phone}`} icon="call" variant="secondary" size="sm" onPress={() => Linking.openURL(`tel:${support.phone}`)} />
          ) : null}
        </Card>
      ) : null}

      <SectionHeader title="Repayment schedule" />
      <Card style={{ paddingVertical: space.xs }}>
        {schedule.map((item, i) => {
          const st = installmentStatus(item.status);
          const paid = item.status === 'paid';
          return (
            <View key={item.installment} style={[styles.scheduleRow, i < schedule.length - 1 && styles.divider]}>
              <View style={[styles.num, paid && { backgroundColor: colors.successBg }]}>
                <Text variant="small" color={paid ? colors.success : colors.textMuted} style={{ fontFamily: font.bold }}>
                  {item.installment}
                </Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text variant="bodyStrong">{naira(paid ? item.amount : item.amount_due)}</Text>
                <Text variant="small" muted>
                  {paid && item.paid_at ? `Paid ${date(item.paid_at.slice(0, 10))}` : `Due ${date(item.due_date)}`}
                </Text>
              </View>
              <Badge label={st.label} tone={st.tone} />
            </View>
          );
        })}
        {l.schedule.length > 6 ? (
          <Pressable accessibilityRole="button" onPress={() => setShowAll((v) => !v)} style={styles.more}>
            <Text variant="small" color={colors.cyanDeep} style={{ fontFamily: font.semibold }}>
              {showAll ? 'Show less' : `Show all ${l.schedule.length} payments`}
            </Text>
          </Pressable>
        ) : null}
      </Card>

      {l.repayments.length ? (
        <>
          <SectionHeader title="Payments made" />
          <Card style={{ paddingVertical: space.xs }}>
            {[...l.repayments].reverse().map((r, i, arr) => (
              <Row
                key={r.id}
                icon="checkmark-circle"
                iconColor={colors.success}
                iconBg={colors.successBg}
                title={naira(r.amount)}
                subtitle={`${dateTime(r.paid_at)} · ${humanize(r.channel)}`}
                last={i === arr.length - 1}
              />
            ))}
          </Card>
        </>
      ) : null}

      <SectionHeader title="Loan terms" />
      <Card style={{ paddingVertical: space.xs }}>
        <Term label="Amount borrowed" value={naira(l.principal)} />
        <Term label="Interest" value={`${naira(l.total_interest)} (${Number(l.interest_rate)}% monthly)`} />
        <Term label="Total to repay" value={naira(l.total_repayable)} />
        <Term label="Repayments" value={`${l.installments_count} × ${CADENCE[l.repayment_cadence] ?? humanize(l.repayment_cadence)}`} />
        <Term label="Tenure" value={`${l.tenure_months} month${l.tenure_months === 1 ? '' : 's'}`} />
        <Term label="Paid out" value={date(l.disbursement_date)} last />
      </Card>
    </Screen>
  );
}

function Term({ label, value, last }: { label: string; value: string; last?: boolean }) {
  return (
    <View style={[styles.term, !last && styles.divider]}>
      <Text variant="small" muted>
        {label}
      </Text>
      <Text variant="bodyStrong" style={{ flexShrink: 1, textAlign: 'right' }}>
        {value}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  between: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: space.sm },
  next: { flexDirection: 'row', alignItems: 'center', gap: space.md, borderWidth: 1.5, borderColor: colors.cyan },
  scheduleRow: { flexDirection: 'row', alignItems: 'center', gap: space.sm, paddingVertical: space.sm, minHeight: 56 },
  divider: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  num: {
    width: 32,
    height: 32,
    borderRadius: radius.sm,
    backgroundColor: colors.surfaceNav,
    alignItems: 'center',
    justifyContent: 'center',
  },
  more: { minHeight: 44, alignItems: 'center', justifyContent: 'center' },
  term: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: space.md, paddingVertical: space.sm, minHeight: 48 },
});
