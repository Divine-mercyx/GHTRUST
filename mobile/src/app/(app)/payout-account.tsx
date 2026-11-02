import Ionicons from '@expo/vector-icons/Ionicons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';

import { banks, wallet } from '@/api/endpoints';
import { ApiError, messageFor } from '@/api/errors';
import { Button } from '@/components/Button';
import { Field } from '@/components/Field';
import { Screen } from '@/components/Screen';
import { SelectField } from '@/components/SelectField';
import { Banner } from '@/components/States';
import { Text } from '@/components/Text';
import { TransactionPinSheet } from '@/components/TransactionPinSheet';
import { digits } from '@/lib/format';
import { keys, useBanks } from '@/lib/queries';
import { colors, radius, space } from '@/theme/tokens';

/**
 * Where withdrawals go. The customer picks a bank and enters the account number, we look
 * up the name so they can confirm it's theirs, and saving needs the transaction PIN
 * (changing the payout account is as sensitive as a withdrawal).
 */
export default function PayoutAccount() {
  const { next } = useLocalSearchParams<{ next?: string }>();
  const queryClient = useQueryClient();
  const bankList = useBanks();
  const [bank, setBank] = useState<{ code: string; name: string } | null>(null);
  const [number, setNumber] = useState('');
  const [askPin, setAskPin] = useState(false);
  const lastLookup = useRef('');

  const resolve = useMutation({ mutationFn: () => banks.resolve(bank!.code, number) });
  const name = resolve.data?.account_name ?? '';

  // Look the name up as soon as bank + 10 digits are in.
  useEffect(() => {
    const k = `${bank?.code}:${number}`;
    if (bank && number.length === 10 && lastLookup.current !== k) {
      lastLookup.current = k;
      resolve.mutate();
    }
  }, [bank, number]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = useMutation({
    mutationFn: (pin: string) =>
      wallet.savePayoutAccount(
        { bank_code: bank!.code, bank_name: bank!.name, account_number: number, account_name: name },
        pin,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.wallet });
      if (next === 'withdraw') router.replace('/withdraw');
      else router.back();
    },
  });

  const pinError = save.error instanceof ApiError && save.error.code.startsWith('TRANSACTION_PIN_');
  const options = (bankList.data ?? []).map((b) => ({ value: b.code, label: b.name }));

  return (
    <Screen
      edges={['bottom']}
      footer={
        <Button
          title="Save account"
          disabled={!name}
          loading={save.isPending}
          onPress={() => {
            save.reset();
            setAskPin(true);
          }}
        />
      }>
      <TransactionPinSheet
        visible={askPin}
        summary={name ? `Send withdrawals to ${name}` : 'Save payout account'}
        onClose={() => setAskPin(false)}
        onPin={(pin) => save.mutateAsync(pin)}
      />
      <Text muted>Money you send from your wallet goes to this account. It stays saved for next time.</Text>
      {bankList.isError ? <Banner message={messageFor(bankList.error)} /> : null}
      {save.error && !pinError ? <Banner message={messageFor(save.error)} /> : null}

      <SelectField
        label="Bank"
        value={bank?.code ?? ''}
        options={options}
        loading={bankList.isPending}
        searchable
        placeholder="Choose your bank"
        onChange={(value, option) => {
          lastLookup.current = '';
          resolve.reset();
          setBank({ code: value, name: option.label });
        }}
      />
      <Field
        label="Account number"
        value={number}
        keyboardType="number-pad"
        maxLength={10}
        placeholder="10-digit NUBAN"
        onChangeText={(t) => {
          const d = digits(t).slice(0, 10);
          if (d !== number) {
            lastLookup.current = '';
            resolve.reset();
            setNumber(d);
          }
        }}
        error={number.length > 0 && number.length < 10 ? 'Account numbers have 10 digits.' : null}
      />

      {resolve.isPending ? (
        <View style={styles.lookup}>
          <ActivityIndicator color={colors.navy} />
          <Text variant="small" muted>
            Checking account…
          </Text>
        </View>
      ) : name ? (
        <View style={[styles.lookup, styles.found]} accessibilityLiveRegion="polite">
          <Ionicons name="checkmark-circle" size={22} color={colors.success} />
          <View style={{ flex: 1 }}>
            <Text variant="small" muted>
              Account name
            </Text>
            <Text variant="bodyStrong">{name}</Text>
          </View>
        </View>
      ) : resolve.isError ? (
        <View style={{ gap: space.xs }}>
          <Banner message={messageFor(resolve.error)} />
          <Button
            title="Try again"
            variant="secondary"
            size="sm"
            icon="refresh"
            onPress={() => {
              lastLookup.current = `${bank?.code}:${number}`;
              resolve.mutate();
            }}
          />
        </View>
      ) : null}

      <Text variant="small" muted>
        Use an account in your own name. If the name above isn&apos;t yours, check the bank and account number.
      </Text>
    </Screen>
  );
}

const styles = StyleSheet.create({
  lookup: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
    padding: space.md,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceNav,
    minHeight: 56,
  },
  found: { backgroundColor: colors.successBg },
});
