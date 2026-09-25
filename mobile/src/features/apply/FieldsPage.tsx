import { View } from 'react-native';

import { AmountField } from '@/components/AmountField';
import { DateField } from '@/components/DateField';
import { Field } from '@/components/Field';
import { SelectField, toOptions } from '@/components/SelectField';
import { digits } from '@/lib/format';
import { space } from '@/theme/tokens';

import type { FieldDef } from './config';
import { getValue, setValue, type Draft } from './draft';

type Props = {
  fields: FieldDef[];
  draft: Draft;
  onChange: (next: Draft) => void;
  errors: Record<string, string>;
  /** A field was edited: its error no longer applies. */
  onEdited?: (key: string) => void;
};

export function FieldsPage({ fields, draft, onChange, errors, onEdited }: Props) {
  return (
    <View style={{ gap: space.lg }}>
      {fields.map((def) => {
        const value = getValue(draft, def);
        const set = (v: string) => {
          onChange(setValue(draft, def, v));
          if (errors[def.key]) onEdited?.(def.key);
        };
        const common = { label: def.label, error: errors[def.key], optional: !def.required };

        switch (def.kind) {
          case 'money':
            return <AmountField key={def.key} label={def.label} value={value} onChange={set} error={errors[def.key]} hint={def.hint} />;
          case 'select': {
            const options = toOptions(def.options ?? []);
            // Keep a pre-filled value that isn't in our list (e.g. from the BVN record).
            if (value && !options.some((o) => o.value === value)) options.unshift({ value, label: value });
            return <SelectField key={def.key} {...common} value={value} options={options} onChange={set} />;
          }
          case 'date':
            return <DateField key={def.key} {...common} value={value} onChange={(iso) => set(iso ?? '')} />;
          case 'integer':
            return (
              <Field
                key={def.key}
                {...common}
                value={value}
                hint={def.hint}
                keyboardType="number-pad"
                maxLength={3}
                onChangeText={(t) => set(digits(t))}
              />
            );
          case 'phone':
            return (
              <Field
                key={def.key}
                {...common}
                value={value}
                keyboardType="phone-pad"
                autoComplete="tel"
                maxLength={14}
                placeholder="0803 123 4567"
                onChangeText={set}
              />
            );
          case 'email':
            return (
              <Field
                key={def.key}
                {...common}
                value={value}
                keyboardType="email-address"
                autoCapitalize="none"
                autoComplete="email"
                autoCorrect={false}
                onChangeText={set}
              />
            );
          case 'multiline':
            return (
              <Field
                key={def.key}
                {...common}
                value={value}
                multiline
                numberOfLines={3}
                maxLength={500}
                style={{ minHeight: 76, textAlignVertical: 'top' }}
                onChangeText={set}
              />
            );
          default:
            return (
              <Field
                key={def.key}
                {...common}
                value={value}
                placeholder={def.placeholder}
                hint={def.hint}
                autoCapitalize={def.kind === 'name' ? 'words' : 'sentences'}
                autoComplete={def.kind === 'name' ? 'name' : undefined}
                maxLength={200}
                onChangeText={set}
              />
            );
        }
      })}
    </View>
  );
}
