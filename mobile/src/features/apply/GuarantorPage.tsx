import Ionicons from '@expo/vector-icons/Ionicons';
import { Pressable, StyleSheet, View } from 'react-native';

import type { CollateralInput, GuarantorInput } from '@/api/types';
import { AmountField } from '@/components/AmountField';
import { Button } from '@/components/Button';
import { Card, SectionHeader } from '@/components/Card';
import { Field } from '@/components/Field';
import { SelectField, toOptions } from '@/components/SelectField';
import { Banner } from '@/components/States';
import { Text } from '@/components/Text';
import { colors, HIT, space } from '@/theme/tokens';

import type { Draft } from './draft';

const RELATIONSHIPS = toOptions(['Spouse', 'Parent', 'Sibling', 'Relative', 'Friend', 'Colleague', 'Employer', 'Business partner', 'Other']);
const COLLATERAL_TYPES = toOptions(['Vehicle', 'Land / property', 'Equipment', 'Inventory / goods', 'Cheque', 'Other']);
const MAX_GUARANTORS = 3;

type Props = { draft: Draft; onChange: (next: Draft) => void; error?: string | null };

export function GuarantorPage({ draft, onChange, error }: Props) {
  const guarantors = draft.guarantors.length ? draft.guarantors : [{ full_name: '' } as GuarantorInput];
  const setG = (list: GuarantorInput[]) => onChange({ ...draft, guarantors: list });
  const setC = (list: CollateralInput[]) => onChange({ ...draft, collaterals: list });
  const patchG = (i: number, patch: Partial<GuarantorInput>) =>
    setG(guarantors.map((g, j) => (j === i ? { ...g, ...patch } : g)));
  const patchC = (i: number, patch: Partial<CollateralInput>) =>
    setC(draft.collaterals.map((c, j) => (j === i ? { ...c, ...patch } : c)));

  return (
    <View style={{ gap: space.md }}>
      {error ? <Banner message={error} /> : null}
      {guarantors.map((g, i) => (
        <Card key={i} style={{ gap: space.md }}>
          <View style={styles.head}>
            <Text variant="heading">Guarantor {i + 1}</Text>
            {guarantors.length > 1 ? (
              <RemoveButton label={`Remove guarantor ${i + 1}`} onPress={() => setG(guarantors.filter((_, j) => j !== i))} />
            ) : null}
          </View>
          <Field label="Full name" value={g.full_name} autoCapitalize="words" onChangeText={(t) => patchG(i, { full_name: t })} />
          <Field
            label="Phone number"
            value={g.phone ?? ''}
            keyboardType="phone-pad"
            maxLength={14}
            onChangeText={(t) => patchG(i, { phone: t })}
          />
          <SelectField label="Relationship to you" value={g.relationship} options={RELATIONSHIPS} onChange={(v) => patchG(i, { relationship: v })} />
          <Field
            label="Address"
            optional
            value={g.address ?? ''}
            multiline
            maxLength={500}
            style={{ minHeight: 64, textAlignVertical: 'top' }}
            onChangeText={(t) => patchG(i, { address: t })}
          />
        </Card>
      ))}
      {guarantors.length < MAX_GUARANTORS ? (
        <Button
          title="Add another guarantor"
          icon="person-add-outline"
          variant="secondary"
          onPress={() => setG([...guarantors, { full_name: '' }])}
        />
      ) : null}

      <SectionHeader title="Collateral (optional)" />
      {draft.collaterals.map((c, i) => (
        <Card key={i} style={{ gap: space.md }}>
          <View style={styles.head}>
            <Text variant="heading">Item {i + 1}</Text>
            <RemoveButton label={`Remove collateral ${i + 1}`} onPress={() => setC(draft.collaterals.filter((_, j) => j !== i))} />
          </View>
          <SelectField label="Type" value={c.collateral_type} options={COLLATERAL_TYPES} onChange={(v) => patchC(i, { collateral_type: v })} />
          <Field label="Description" value={c.description} maxLength={500} onChangeText={(t) => patchC(i, { description: t })} />
          <AmountField
            label="Estimated value (optional)"
            value={c.estimated_value ? String(c.estimated_value).replace(/\.0+$/, '') : ''}
            onChange={(v) => patchC(i, { estimated_value: v || null })}
          />
        </Card>
      ))}
      <Button
        title={draft.collaterals.length ? 'Add another item' : 'Add collateral'}
        icon="add"
        variant="ghost"
        onPress={() => setC([...draft.collaterals, { collateral_type: 'Other', description: '' }])}
      />
    </View>
  );
}

function RemoveButton({ label, onPress }: { label: string; onPress: () => void }) {
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={label} onPress={onPress} hitSlop={8} style={styles.remove}>
      <Ionicons name="trash-outline" size={20} color={colors.error} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  head: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  remove: { width: HIT, height: HIT, alignItems: 'center', justifyContent: 'center', marginRight: -space.sm },
});
