import Ionicons from '@expo/vector-icons/Ionicons';
import { Platform, StyleSheet, TextInput, View } from 'react-native';

import { PressableScale } from '@/components/home/PressableScale';
import { Text } from '@/components/Text';
import { digits, groupThousands, naira } from '@/lib/format';
import { colors, font, radius, space } from '@/theme/tokens';

type Props = {
  /** Plain digits (whole naira). */
  value: string;
  onChange: (digitsOnly: string) => void;
  /** Quick amounts, in naira. */
  presets: number[];
  /** Adds an "All" chip that fills this amount (e.g. the whole balance). */
  max?: number;
  /** − / + step, in naira. */
  step?: number;
  error?: string | null;
  label?: string;
};

/**
 * Large centred amount with − / + steppers and quick-amount chips (the chosen one in gold).
 * Typing works too; the number is grouped as you type.
 */
export function AmountStepper({ value, onChange, presets, max, step = 1000, error, label = 'Amount' }: Props) {
  const n = Number(value || 0);
  // Size the input to the number, so the ₦ sits right next to it.
  const width = Math.max(1, groupThousands(value).length) * 24 + 12;
  const set = (next: number) => onChange(String(Math.max(0, Math.floor(next))));
  const chips = [...presets.filter((p) => max === undefined || p <= max).map((p) => ({ label: naira(p), amount: p }))];
  if (max !== undefined && max > 0) chips.push({ label: 'All', amount: Math.floor(max) });

  return (
    <View style={styles.wrap}>
      <Text variant="small" muted align="center">
        {label}
      </Text>
      <View style={styles.row}>
        <Stepper icon="remove" label={`Less by ${naira(step)}`} disabled={n <= 0} onPress={() => set(n - step)} />
        <View style={styles.amount}>
          <Text style={styles.currency}>₦</Text>
          <TextInput
            value={groupThousands(value)}
            onChangeText={(t) => onChange(digits(t).replace(/^0+(?=\d)/, '').slice(0, 12))}
            keyboardType="number-pad"
            placeholder="0"
            placeholderTextColor={colors.textFaint}
            accessibilityLabel={label}
            accessibilityHint={error ?? undefined}
            maxFontSizeMultiplier={1.2}
            style={[styles.input, { width }]}
          />
        </View>
        <Stepper
          icon="add"
          label={`More by ${naira(step)}`}
          disabled={max !== undefined && n + step > max}
          onPress={() => set(n + step)}
        />
      </View>
      {error ? (
        <Text variant="small" color={colors.error} align="center" accessibilityLiveRegion="polite">
          {error}
        </Text>
      ) : null}
      <View style={styles.chips}>
        {chips.map((c) => {
          const on = n === c.amount;
          return (
            <PressableScale
              key={c.label}
              accessibilityRole="button"
              accessibilityState={{ selected: on }}
              accessibilityLabel={c.label === 'All' ? `All, ${naira(c.amount)}` : c.label}
              onPress={() => set(c.amount)}
              style={[styles.chip, on && styles.chipOn]}>
              <Text variant="small" color={colors.navy} style={{ fontFamily: on ? font.bold : font.semibold }}>
                {c.label}
              </Text>
            </PressableScale>
          );
        })}
      </View>
    </View>
  );
}

function Stepper({
  icon,
  label,
  onPress,
  disabled,
}: {
  icon: 'add' | 'remove';
  label: string;
  onPress: () => void;
  disabled?: boolean;
}) {
  return (
    <PressableScale
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={[styles.stepper, disabled && { opacity: 0.4 }]}>
      <Ionicons name={icon} size={22} color={colors.navy} />
    </PressableScale>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: space.sm },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  amount: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center' },
  currency: { fontFamily: font.bold, fontSize: 26, color: colors.textMuted, marginRight: 4 },
  input: {
    maxWidth: '85%',
    textAlign: 'center',
    fontFamily: font.extrabold,
    fontSize: 38,
    color: colors.text,
    paddingVertical: space.xs,
    ...(Platform.OS === 'web' ? ({ outlineStyle: 'none' } as object) : null),
  },
  stepper: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: colors.surfaceNav,
    alignItems: 'center',
    justifyContent: 'center',
  },
  chips: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'center', gap: space.xs },
  chip: {
    height: 38,
    paddingHorizontal: space.md,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceNav,
    alignItems: 'center',
    justifyContent: 'center',
  },
  chipOn: { backgroundColor: colors.highlight },
});
