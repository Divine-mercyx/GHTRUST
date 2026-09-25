import { forwardRef, useState } from 'react';
import { Platform, StyleSheet, TextInput, View, type TextInputProps } from 'react-native';

import { colors, font, HIT, radius, space } from '@/theme/tokens';

import { Text } from './Text';

type Props = TextInputProps & {
  label: string;
  error?: string | null;
  hint?: string;
  prefix?: string;
  optional?: boolean;
};

export const Field = forwardRef<TextInput, Props>(function Field(
  { label, error, hint, prefix, optional, style, onFocus, onBlur, ...input },
  ref,
) {
  const [focused, setFocused] = useState(false);
  const borderColor = error ? colors.error : focused ? colors.cyan : colors.border;
  return (
    <View style={styles.wrap}>
      <Text variant="small" style={styles.label}>
        {label}
        {optional ? <Text variant="small" muted>{'  (optional)'}</Text> : null}
      </Text>
      <View style={[styles.box, { borderColor }, focused && styles.focused]}>
        {prefix ? (
          <Text variant="bodyStrong" muted style={styles.prefix}>
            {prefix}
          </Text>
        ) : null}
        <TextInput
          ref={ref}
          accessibilityLabel={label}
          accessibilityHint={error ?? hint}
          placeholderTextColor={colors.textFaint}
          selectionColor={colors.cyan}
          maxFontSizeMultiplier={1.4}
          onFocus={(e) => {
            setFocused(true);
            onFocus?.(e);
          }}
          onBlur={(e) => {
            setFocused(false);
            onBlur?.(e);
          }}
          style={[styles.input, style]}
          {...input}
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
});

const styles = StyleSheet.create({
  wrap: { gap: 6 },
  label: { fontFamily: font.semibold },
  box: {
    flexDirection: 'row',
    alignItems: 'center',
    minHeight: HIT + 4,
    borderWidth: 1.5,
    borderRadius: radius.md,
    backgroundColor: colors.card,
    paddingHorizontal: space.md,
  },
  focused: { backgroundColor: '#FBFDFF' },
  prefix: { marginRight: space.xs },
  input: {
    flex: 1,
    minWidth: 0,
    ...(Platform.OS === 'web' ? ({ outlineStyle: 'none' } as object) : null),
    fontFamily: font.semibold,
    fontSize: 16,
    color: colors.text,
    paddingVertical: space.sm,
  },
});
