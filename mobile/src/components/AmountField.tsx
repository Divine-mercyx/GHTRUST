import { Platform, StyleSheet, TextInput, View } from 'react-native';

import { digits, groupThousands } from '@/lib/format';
import { colors, font, radius, space } from '@/theme/tokens';

import { Text } from './Text';

/** Large naira amount input: whole naira, grouped as you type. `value` is plain digits. */
export function AmountField({
  value,
  onChange,
  label,
  error,
  hint,
  autoFocus,
}: {
  value: string;
  onChange: (digitsOnly: string) => void;
  label: string;
  error?: string | null;
  hint?: string;
  autoFocus?: boolean;
}) {
  return (
    <View style={{ gap: 6 }}>
      <Text variant="small" style={{ fontFamily: font.semibold }}>
        {label}
      </Text>
      <View style={[styles.box, error ? { borderColor: colors.error } : null]}>
        <Text style={styles.currency}>₦</Text>
        <TextInput
          value={groupThousands(value)}
          onChangeText={(t) => onChange(digits(t).replace(/^0+(?=\d)/, '').slice(0, 12))}
          keyboardType="number-pad"
          placeholder="0"
          placeholderTextColor={colors.textFaint}
          autoFocus={autoFocus}
          accessibilityLabel={label}
          accessibilityHint={error ?? hint}
          maxFontSizeMultiplier={1.3}
          style={styles.input}
        />
      </View>
      {error ? (
        <Text variant="small" color={colors.error} accessibilityLiveRegion="polite">
          {error}
        </Text>
      ) : hint ? (
        <Text variant="small" muted>
          {hint}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  box: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1.5,
    borderColor: colors.border,
    borderRadius: radius.lg,
    backgroundColor: colors.card,
    paddingHorizontal: space.lg,
    minHeight: 72,
  },
  currency: { fontFamily: font.bold, fontSize: 28, color: colors.textMuted, marginRight: space.xs },
  input: {
    flex: 1,
    minWidth: 0, // web inputs have an intrinsic width that flex won't shrink below
    fontFamily: font.extrabold,
    fontSize: 32,
    color: colors.text,
    paddingVertical: space.sm,
    ...(Platform.OS === 'web' ? ({ outlineStyle: 'none' } as object) : null),
  },
});
