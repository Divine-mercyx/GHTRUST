import Ionicons from '@expo/vector-icons/Ionicons';
import { useMutation } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';

import { banks } from '@/api/endpoints';
import { messageFor } from '@/api/errors';
import { Button } from '@/components/Button';
import { Field } from '@/components/Field';
import { SelectField } from '@/components/SelectField';
import { Banner } from '@/components/States';
import { Text } from '@/components/Text';
import { digits } from '@/lib/format';
import { useBanks } from '@/lib/queries';
import { colors, radius, space } from '@/theme/tokens';

import type { Draft } from './draft';

type Props = { draft: Draft; onChange: (next: Draft) => void; error?: string | null };

/**
 * Bank + account number, then a name enquiry so the customer confirms the
 * payout account is theirs before the loan is disbursed to it.
 */
export function BankPage({ draft, onChange, error }: Props) {
  const bankList = useBanks();
  const code = draft.form.bank_code ?? '';
  const number = draft.form.bank_account_number ?? '';
  const name = draft.form.bank_account_name ?? '';
  const lastLookup = useRef('');

  const resolve = useMutation({
    mutationFn: () => banks.resolve(code, number),
    onSuccess: (res) => onChange({ ...draft, form: { ...draft.form, bank_account_name: res.account_name } }),
  });

  // Look the name up as soon as bank + 10 digits are in.
  useEffect(() => {
    const k = `${code}:${number}`;
    if (code && number.length === 10 && lastLookup.current !== k && !name) {
      lastLookup.current = k;
      resolve.mutate();
    }
  }, [code, number]); // eslint-disable-line react-hooks/exhaustive-deps

  const set = (patch: Record<string, string>) => onChange({ ...draft, form: { ...draft.form, ...patch } });
  const options = (bankList.data ?? []).map((b) => ({ value: b.code, label: b.name }));
  if (code && !options.some((o) => o.value === code) && draft.form.bank_name) {
    options.unshift({ value: code, label: draft.form.bank_name });
  }

  return (
    <View style={{ gap: space.lg }}>
      {bankList.isError ? <Banner message={messageFor(bankList.error)} /> : null}
      {error ? <Banner message={error} /> : null}
      <SelectField
        label="Bank"
        value={code}
        options={options}
        loading={bankList.isPending}
        searchable
        placeholder="Choose your bank"
        onChange={(value, option) => {
          lastLookup.current = '';
          resolve.reset();
          set({ bank_code: value, bank_name: option.label, bank_account_name: '' });
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
            set({ bank_account_number: d, bank_account_name: '' });
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
              lastLookup.current = `${code}:${number}`;
              resolve.mutate();
            }}
          />
        </View>
      ) : null}

      <Text variant="small" muted>
        The loan can only be paid into an account in your own name. If the name above isn't yours, check the details.
      </Text>
    </View>
  );
}

export const bankComplete = (d: Draft) =>
  !!d.form.bank_code && (d.form.bank_account_number ?? '').length === 10 && !!d.form.bank_account_name;

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
