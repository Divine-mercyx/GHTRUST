import Ionicons from '@expo/vector-icons/Ionicons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import * as Haptics from 'expo-haptics';
import { router } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { Platform, ScrollView, StyleSheet, View } from 'react-native';
import Animated, { ZoomIn } from 'react-native-reanimated';

import { newIdempotencyKey } from '@/api/client';
import { wallet } from '@/api/endpoints';
import { ApiError, messageFor } from '@/api/errors';
import type { PayoutRecipient } from '@/api/types';
import { ActionSheet } from '@/components/ActionSheet';
import { AmountStepper } from '@/components/AmountStepper';
import { Button } from '@/components/Button';
import { Field } from '@/components/Field';
import { PressableScale } from '@/components/home/PressableScale';
import { Screen } from '@/components/Screen';
import { Banner, CardSkeleton, EmptyState, ErrorState } from '@/components/States';
import { Text } from '@/components/Text';
import { TransactionPinSheet } from '@/components/TransactionPinSheet';
import { shortAccount } from '@/lib/activity';
import { dateTime, naira } from '@/lib/format';
import { MIN_WITHDRAWAL, withdrawalError } from '@/lib/loans';
import { keys, useRecipients, useWallet } from '@/lib/queries';
import { colors, font, radius, shadow, space } from '@/theme/tokens';

const MIN = MIN_WITHDRAWAL;
const PRESETS = [1000, 5000, 10000, 20000];
// Same rule as the API: what every bank's narration field accepts.
const NOTE_MAX = 30;
const NOTE_CHARS = /^[A-Za-z0-9 .,'&()/-]*$/;

/** Send wallet money to one of the customer's saved bank accounts (a withdrawal). */
export default function SendMoney() {
  const queryClient = useQueryClient();
  const summary = useWallet();
  const recipients = useRecipients();
  const [amount, setAmount] = useState('');
  const [note, setNote] = useState('');
  const [chosen, setChosen] = useState<string | null>(null);
  const [askPin, setAskPin] = useState(false);
  const [manage, setManage] = useState<PayoutRecipient | null>(null);
  // One key per send attempt: a retry after a timeout replays, never pays out twice.
  const key = useRef(newIdempotencyKey());

  const list = recipients.data ?? [];
  const to = list.find((r) => r.id === chosen) ?? list.find((r) => r.current) ?? list[0];
  const narration = note.trim().replace(/\s+/g, ' ');

  const send = useMutation({
    mutationFn: (pin: string) =>
      wallet.withdraw(Number(amount).toFixed(2), pin, key.current, to?.id, narration || undefined),
    onSuccess: () => {
      if (Platform.OS !== 'web')
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => undefined);
      queryClient.invalidateQueries({ queryKey: keys.wallet });
      queryClient.invalidateQueries({ queryKey: keys.transactions });
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => wallet.removeRecipient(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.recipients }),
  });

  // Changing the amount, the account or the note is a new send → new key.
  useEffect(() => {
    if (!send.isPending) key.current = newIdempotencyKey();
  }, [amount, to?.id, narration]); // eslint-disable-line react-hooks/exhaustive-deps

  const w = summary.data;

  if (send.isSuccess) {
    return (
      <Screen
        edges={['bottom']}
        scroll={false}
        footer={
          <>
            <Button title="Done" onPress={() => router.back()} />
            <Button
              title="View receipt"
              variant="ghost"
              onPress={() => router.replace(`/transactions/w_${send.data.id}`)}
            />
          </>
        }>
        <View style={styles.success}>
          <Animated.View entering={ZoomIn.springify()} style={styles.tick}>
            <Ionicons name="paper-plane" size={36} color={colors.white} />
          </Animated.View>
          <Text variant="title" align="center">
            Money on its way
          </Text>
          <Text muted align="center">
            {naira(send.data.amount)} is being sent to {to?.account_name ?? 'your account'} at {to?.bank_name ?? 'your bank'}{' '}
            {to ? `····${to.account_number_masked.slice(-4)}` : ''}. Most transfers arrive within minutes.
          </Text>
        </View>
      </Screen>
    );
  }

  if (summary.isPending || recipients.isPending) {
    return (
      <Screen edges={['bottom']}>
        <CardSkeleton />
      </Screen>
    );
  }
  if (summary.isError || !w || recipients.isError) {
    return (
      <Screen edges={['bottom']}>
        <ErrorState
          error={summary.error ?? recipients.error}
          onRetry={() => {
            summary.refetch();
            recipients.refetch();
          }}
        />
      </Screen>
    );
  }

  if (!to) {
    return (
      <Screen edges={['bottom']}>
        <EmptyState
          icon="business-outline"
          title="Add a bank account"
          body="Save the account to send money to. Your saved accounts stay here for next time."
          action={{ title: 'Add bank account', onPress: () => router.replace('/payout-account?next=withdraw') }}
        />
      </Screen>
    );
  }

  const balance = w.available_balance;
  const value = Number(amount || 0);
  const onHold = w.withdrawals_blocked_until ? new Date(w.withdrawals_blocked_until) > new Date() : false;
  const insufficient = send.error instanceof ApiError && send.error.code === 'INSUFFICIENT_FUNDS';
  // Wrong or locked PINs are shown in the PIN sheet itself.
  const pinError = send.error instanceof ApiError && send.error.code.startsWith('TRANSACTION_PIN_');
  const error = withdrawalError(amount, balance);
  const noteError = NOTE_CHARS.test(narration) ? null : "Use letters, numbers, spaces and . , ' & ( ) / - only";

  return (
    <Screen
      edges={['bottom']}
      onRefresh={() => {
        summary.refetch();
        recipients.refetch();
      }}
      refreshing={summary.isRefetching}
      footer={
        <Button
          title={value > 0 ? `Send ${naira(value)}` : 'Send'}
          disabled={onHold || !!error || !!noteError || value < MIN}
          loading={send.isPending}
          onPress={() => {
            send.reset();
            setAskPin(true);
          }}
        />
      }>
      <TransactionPinSheet
        visible={askPin}
        summary={`Send ${naira(value)} to ${to.account_name ?? 'your account'} (${to.bank_name ?? 'bank'} ····${to.account_number_masked.slice(-4)})${narration ? `: "${narration}"` : ''}`}
        onClose={() => setAskPin(false)}
        onPin={(pin) => send.mutateAsync(pin)}
      />
      <ActionSheet
        visible={!!manage}
        title={manage ? `${manage.account_name ?? 'Account'} · ${manage.bank_name ?? 'Bank'}` : ''}
        actions={
          manage && !manage.current
            ? [{ label: 'Remove this account', icon: 'trash-outline', onPress: () => remove.mutate(manage.id) }]
            : [{ label: 'Add another account', icon: 'add-circle-outline', onPress: () => router.push('/payout-account?next=withdraw') }]
        }
        onClose={() => setManage(null)}
      />

      {onHold ? (
        <Banner
          tone="warning"
          message={`For your security, sending money is paused until ${dateTime(w.withdrawals_blocked_until)} after signing in without your old phone.`}
        />
      ) : null}
      {send.error && !pinError && !insufficient ? <Banner message={messageFor(send.error)} /> : null}
      {insufficient ? <Banner tone="warning" message="Your balance changed. Check the amount and try again." /> : null}
      {remove.error ? <Banner message={messageFor(remove.error)} /> : null}

      <Text variant="bodyStrong">Send to</Text>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.recipients}
        style={styles.recipientScroll}>
        {list.map((r) => (
          <RecipientChip
            key={r.id}
            recipient={r}
            selected={r.id === to.id}
            onPress={() => setChosen(r.id)}
            onLongPress={() => setManage(r)}
          />
        ))}
        <PressableScale
          accessibilityRole="button"
          accessibilityLabel="Add a bank account"
          onPress={() => router.push('/payout-account?next=withdraw')}
          style={[styles.chip, styles.addChip]}>
          <View style={[styles.avatar, styles.addAvatar]}>
            <Ionicons name="add" size={22} color={colors.navy} />
          </View>
          <Text variant="small" style={styles.chipName} numberOfLines={1}>
            Add
          </Text>
        </PressableScale>
      </ScrollView>
      <Text variant="small" muted>
        {to.account_name ?? 'Account'} · {to.bank_name ?? 'Bank'} {shortAccount(to.account_number_masked)}
      </Text>

      <View style={styles.amountCard}>
        <AmountStepper
          value={amount}
          onChange={setAmount}
          presets={PRESETS}
          max={balance >= MIN ? balance : undefined}
          error={error}
          label="How much would you like to send?"
        />
        <Text variant="small" muted align="center">
          Available {naira(balance, { kobo: true })}
        </Text>
      </View>

      <Field
        label="Note"
        optional
        value={note}
        onChangeText={setNote}
        maxLength={NOTE_MAX}
        placeholder="e.g. Rent for May"
        autoCapitalize="sentences"
        returnKeyType="done"
        error={noteError}
        hint={`The recipient sees this on their bank statement · ${narration.length}/${NOTE_MAX}`}
      />
    </Screen>
  );
}

function RecipientChip({
  recipient,
  selected,
  onPress,
  onLongPress,
}: {
  recipient: PayoutRecipient;
  selected: boolean;
  onPress: () => void;
  onLongPress: () => void;
}) {
  const name = recipient.account_name ?? recipient.bank_name ?? 'Account';
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join('');
  return (
    <PressableScale
      accessibilityRole="radio"
      accessibilityState={{ selected }}
      accessibilityLabel={`${name}, ${recipient.bank_name ?? 'bank'} ending ${recipient.account_number_masked.slice(-4)}`}
      accessibilityHint="Long press to remove"
      onPress={onPress}
      onLongPress={onLongPress}
      style={[styles.chip, selected && styles.chipOn]}>
      <View style={[styles.avatar, selected && styles.avatarOn]}>
        <Text variant="bodyStrong" color={selected ? colors.navy : colors.white} style={{ fontFamily: font.bold }}>
          {initials || '₦'}
        </Text>
      </View>
      <Text variant="small" style={styles.chipName} numberOfLines={1}>
        {name.split(/\s+/)[0]}
      </Text>
      <Text variant="small" muted style={styles.chipBank} numberOfLines={1}>
        •••• {recipient.account_number_masked.slice(-4)}
      </Text>
    </PressableScale>
  );
}

const styles = StyleSheet.create({
  recipientScroll: { marginHorizontal: -space.lg },
  recipients: { gap: space.sm, paddingHorizontal: space.lg, paddingVertical: space.xs },
  chip: {
    width: 104,
    alignItems: 'center',
    gap: 4,
    paddingVertical: space.sm,
    paddingHorizontal: space.xs,
    borderRadius: radius.lg,
    backgroundColor: colors.card,
    borderWidth: 2,
    borderColor: 'transparent',
    ...shadow,
  },
  chipOn: { borderColor: colors.highlight },
  addChip: { borderStyle: 'dashed', borderColor: colors.borderStrong, shadowOpacity: 0, elevation: 0 },
  avatar: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: colors.navy,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarOn: { backgroundColor: colors.highlight },
  addAvatar: { backgroundColor: colors.surfaceNav },
  chipName: { fontFamily: font.semibold, maxWidth: '100%' },
  chipBank: { fontSize: 11, lineHeight: 14, maxWidth: '100%' },
  amountCard: {
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    padding: space.lg,
    gap: space.sm,
    marginTop: space.xs,
    ...shadow,
  },
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
