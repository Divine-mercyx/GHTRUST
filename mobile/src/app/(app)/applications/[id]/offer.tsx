import Ionicons from '@expo/vector-icons/Ionicons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import * as Haptics from 'expo-haptics';
import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Platform, Pressable, StyleSheet, View } from 'react-native';
import Animated, { FadeIn, ZoomIn } from 'react-native-reanimated';

import { legal } from '@/api/endpoints';
import { ApiError, messageFor } from '@/api/errors';
import type { LoanOffer } from '@/api/types';
import { Button } from '@/components/Button';
import { Card, SectionHeader } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { Banner, CardSkeleton, ErrorState } from '@/components/States';
import { Text } from '@/components/Text';
import { TransactionPinSheet } from '@/components/TransactionPinSheet';
import { date, dateTime, naira, relativeDue } from '@/lib/format';
import { keys, useLoanOffer } from '@/lib/queries';
import { CADENCE } from '@/lib/status';
import { colors, font, radius, space } from '@/theme/tokens';

const METHOD: Record<string, string> = { flat: 'flat', reducing_balance: 'on the reducing balance' };

/**
 * The approved loan's key facts and agreement. The loan is only paid out after the
 * customer accepts here with their transaction PIN (their e-signature).
 */
export default function LoanOfferScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const queryClient = useQueryClient();
  const offer = useLoanOffer(id);
  const [agreed, setAgreed] = useState(false);
  const [askPin, setAskPin] = useState(false);
  const [showSchedule, setShowSchedule] = useState(true);
  const [showAgreement, setShowAgreement] = useState(false);

  const reject = useMutation({
    mutationFn: () => legal.rejectOffer(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.application(id) });
      queryClient.invalidateQueries({ queryKey: keys.applications });
      router.back();
    },
  });

  const accept = useMutation({
    mutationFn: (pin: string) => legal.acceptOffer(id, offer.data!.terms_hash, pin),
    onSuccess: (accepted) => {
      if (Platform.OS !== 'web')
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => undefined);
      queryClient.setQueryData(keys.offer(id), accepted);
      queryClient.invalidateQueries({ queryKey: keys.application(id) });
      queryClient.invalidateQueries({ queryKey: keys.applications });
    },
    onError: (err) => {
      if (err instanceof ApiError && err.code === 'OFFER_CHANGED') {
        setAgreed(false);
        offer.refetch();
      }
    },
  });

  if (accept.isSuccess) {
    return (
      <Screen edges={['bottom']} scroll={false} footer={<Button title="Done" onPress={() => router.back()} />}>
        <View style={styles.success}>
          <Animated.View entering={ZoomIn.springify()} style={styles.tick}>
            <Ionicons name="checkmark" size={40} color={colors.white} />
          </Animated.View>
          <Text variant="title" align="center">
            Offer accepted
          </Text>
          <Text muted align="center">
            We'll pay {naira(accept.data.principal)} into your {accept.data.payout_bank ?? 'bank'} account shortly and
            let you know as soon as it's sent.
          </Text>
        </View>
      </Screen>
    );
  }
  if (offer.isPending) {
    return (
      <Screen edges={['bottom']}>
        <CardSkeleton lines={3} />
        <CardSkeleton lines={6} />
      </Screen>
    );
  }
  if (offer.isError || !offer.data) {
    return (
      <Screen edges={['bottom']}>
        <ErrorState error={offer.error} onRetry={() => offer.refetch()} />
      </Screen>
    );
  }

  const o = offer.data;
  const accepted = !!o.accepted_at;
  const firstDue = o.schedule[0];
  // Wrong or locked PINs are shown in the PIN sheet itself.
  const pinError = accept.error instanceof ApiError && accept.error.code.startsWith('TRANSACTION_PIN_');

  return (
    <Screen
      edges={['bottom']}
      onRefresh={() => offer.refetch()}
      refreshing={offer.isRefetching}
      footer={
        accepted ? null : (
          <View style={styles.footer}>
            <Button
              title="Decline offer"
              variant="secondary"
              loading={reject.isPending}
              disabled={accept.isPending}
              onPress={() => reject.mutate()}
            />
            <Button
              title="Accept offer"
              icon="checkmark-circle"
              disabled={!agreed}
              loading={accept.isPending}
              onPress={() => {
                accept.reset();
                setAskPin(true);
              }}
            />
          </View>
        )
      }>
      <TransactionPinSheet
        visible={askPin}
        summary={`Accept your ${naira(o.principal)} ${o.product_name} offer`}
        onClose={() => setAskPin(false)}
        onPin={(pin) => accept.mutateAsync(pin)}
      />
      {o.draft ? <Banner tone="info" message="Draft agreement wording, pending final legal review." /> : null}
      {reject.error ? <Banner message={messageFor(reject.error)} /> : null}
      {accept.error && !pinError ? <Banner message={messageFor(accept.error)} /> : null}
      {accepted ? (
        <Banner
          tone="info"
          message={`You accepted this offer on ${dateTime(o.accepted_at)}. We'll pay it out shortly.`}
        />
      ) : null}

      <View style={styles.hero}>
        <Text variant="caption" color={colors.cyan}>
          {o.product_name.toUpperCase()} OFFER
        </Text>
        <Text variant="small" color="rgba(255,255,255,0.75)">
          You'll receive
        </Text>
        <Text variant="display" color={colors.white}>
          {naira(o.principal)}
        </Text>
        <Text variant="small" color="rgba(255,255,255,0.75)">
          {o.payout_account_masked
            ? `Into ${o.payout_bank ?? 'your bank'} ${o.payout_account_masked}${o.payout_account_name ? ` · ${o.payout_account_name}` : ''}`
            : 'Into the bank account on your application'}
        </Text>
        <View style={styles.heroRow}>
          <HeroFact label="Total to repay" value={naira(o.total_repayable)} />
          <HeroFact label={`${o.installments} payments of`} value={naira(o.first_payment)} />
        </View>
        {firstDue ? (
          <Text variant="small" color="rgba(255,255,255,0.85)" style={{ marginTop: space.xs }}>
            First payment: {naira(firstDue.amount)} on {date(firstDue.due_date)}
            {relativeDue(firstDue.due_date) ? ` (${relativeDue(firstDue.due_date)})` : ''}
          </Text>
        ) : null}
      </View>

      <SectionHeader title="Key facts" />
      <Card style={{ paddingVertical: space.xs }}>
        <Fact label="Loan amount" value={naira(o.principal)} />
        <Fact label="Duration" value={`${o.tenure_months} month${o.tenure_months === 1 ? '' : 's'}`} />
        <Fact label="Repayments" value={`${o.installments} × ${CADENCE[o.cadence]?.toLowerCase() ?? o.cadence}`} />
        <Fact
          label="Interest rate"
          value={`${Number(o.interest_rate_pct_monthly)}% a month, ${METHOD[o.interest_method] ?? o.interest_method}`}
        />
        <Fact label="Total interest" value={naira(o.total_interest)} />
        <Fact label={`Processing fee (${Number(o.processing_fee_pct)}%)`} value={naira(o.processing_fee)} />
        <Fact label="Total cost of credit" value={naira(o.total_cost_of_credit)} strong />
        <Fact label="Total to repay" value={naira(o.total_repayable)} strong />
        <Fact
          label="Late payment charge"
          value={o.late_charge_pct_daily ? `${Number(o.late_charge_pct_daily)}% a day of the overdue amount` : 'None'}
          last
        />
      </Card>

      <Expander title="Repayment schedule" open={showSchedule} onToggle={() => setShowSchedule((v) => !v)} />
      {showSchedule ? (
        <Animated.View entering={FadeIn.duration(200)}>
          <Card style={{ paddingVertical: space.xs }}>
            {o.schedule.map((line, i) => (
              <Fact
                key={line.installment}
                label={`${line.installment}. ${date(line.due_date)}`}
                value={naira(line.amount)}
                last={i === o.schedule.length - 1}
              />
            ))}
          </Card>
          <Text variant="small" muted style={styles.note}>
            Dates are estimated from today. Final dates are set from the day the loan is paid out. After that, we&apos;ll
            remind you before each payment is due.
          </Text>
        </Animated.View>
      ) : null}

      <Expander title="Loan agreement" open={showAgreement} onToggle={() => setShowAgreement((v) => !v)} />
      {showAgreement ? <Agreement offer={o} /> : null}

      {accepted ? null : (
        <Pressable
          accessibilityRole="checkbox"
          accessibilityState={{ checked: agreed }}
          onPress={() => setAgreed((a) => !a)}
          style={styles.agree}>
          <View style={[styles.box, agreed && styles.boxOn]}>
            {agreed ? <Ionicons name="checkmark" size={16} color={colors.white} /> : null}
          </View>
          <Text variant="small" style={{ flex: 1 }}>
            I've read the key facts and the loan agreement, and I accept this loan on these terms.
          </Text>
        </Pressable>
      )}
    </Screen>
  );
}

function Agreement({ offer }: { offer: LoanOffer }) {
  return (
    <Animated.View entering={FadeIn.duration(200)}>
      <Card style={{ gap: space.md }}>
        {offer.agreement.map((s) => (
          <View key={s.heading} style={{ gap: 4 }}>
            <Text variant="bodyStrong">{s.heading}</Text>
            <Text variant="small" style={{ lineHeight: 21 }}>
              {s.body}
            </Text>
          </View>
        ))}
        <Text variant="small" muted>
          Agreement version {offer.agreement_version}. See also the{' '}
          <Text variant="small" color={colors.cyanDeep} onPress={() => router.push('/legal/terms')}>
            Terms of Use
          </Text>
          .
        </Text>
      </Card>
    </Animated.View>
  );
}

function HeroFact({ label, value }: { label: string; value: string }) {
  return (
    <View style={{ flex: 1, gap: 2 }}>
      <Text variant="small" color="rgba(255,255,255,0.75)" numberOfLines={1}>
        {label}
      </Text>
      <Text variant="bodyStrong" color={colors.white} style={{ fontFamily: font.bold }}>
        {value}
      </Text>
    </View>
  );
}

function Fact({ label, value, strong, last }: { label: string; value: string; strong?: boolean; last?: boolean }) {
  return (
    <View style={[styles.fact, !last && styles.divider]}>
      <Text variant="small" muted style={{ flex: 1 }}>
        {label}
      </Text>
      <Text variant={strong ? 'bodyStrong' : 'small'} style={styles.factValue}>
        {value}
      </Text>
    </View>
  );
}

function Expander({ title, open, onToggle }: { title: string; open: boolean; onToggle: () => void }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ expanded: open }}
      onPress={onToggle}
      style={styles.expander}>
      <Text variant="caption" muted>
        {title.toUpperCase()}
      </Text>
      <Ionicons name={open ? 'chevron-up' : 'chevron-down'} size={18} color={colors.textMuted} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  footer: { gap: space.sm },
  hero: { backgroundColor: colors.navy, borderRadius: radius.xl - 4, padding: space.xl, gap: 4 },
  heroRow: {
    flexDirection: 'row',
    gap: space.md,
    marginTop: space.md,
    paddingTop: space.md,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: 'rgba(255,255,255,0.2)',
  },
  fact: { flexDirection: 'row', alignItems: 'center', gap: space.md, paddingVertical: space.sm },
  factValue: { textAlign: 'right', flexShrink: 1 },
  divider: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  expander: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingTop: space.md,
    paddingHorizontal: space.xs,
    minHeight: 44,
  },
  note: { paddingHorizontal: space.xs, marginTop: space.xs },
  agree: { flexDirection: 'row', gap: space.sm, alignItems: 'flex-start', paddingVertical: space.sm, minHeight: 48 },
  box: {
    width: 24,
    height: 24,
    borderRadius: 6,
    borderWidth: 2,
    borderColor: colors.borderStrong,
    alignItems: 'center',
    justifyContent: 'center',
  },
  boxOn: { backgroundColor: colors.navy, borderColor: colors.navy },
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
