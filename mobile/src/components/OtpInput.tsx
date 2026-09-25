import { useEffect, useRef } from 'react';
import { Platform, Pressable, StyleSheet, TextInput, View } from 'react-native';

import { digits } from '@/lib/format';
import { colors, font, radius } from '@/theme/tokens';

import { Text } from './Text';

type Props = {
  value: string;
  onChange: (v: string) => void;
  length?: number;
  error?: boolean;
  autoFocus?: boolean;
};

/**
 * One hidden input behind N boxes: paste and SMS autofill (iOS one-time-code,
 * Android SMS retriever via autoComplete) fill every box at once.
 */
export function OtpInput({ value, onChange, length = 6, error, autoFocus = true }: Props) {
  const ref = useRef<TextInput>(null);
  useEffect(() => {
    if (autoFocus) setTimeout(() => ref.current?.focus(), 250);
  }, [autoFocus]);

  return (
    <Pressable onPress={() => ref.current?.focus()} accessible={false}>
      <View style={styles.row}>
        {Array.from({ length }, (_, i) => {
          const active = i === Math.min(value.length, length - 1);
          return (
            <View
              key={i}
              style={[
                styles.cell,
                active && styles.active,
                !!value[i] && styles.filled,
                error && styles.error,
              ]}>
              <Text style={styles.char}>{value[i] ?? ''}</Text>
            </View>
          );
        })}
      </View>
      <TextInput
        ref={ref}
        value={value}
        onChangeText={(t) => onChange(digits(t).slice(0, length))}
        keyboardType="number-pad"
        textContentType="oneTimeCode"
        autoComplete={Platform.OS === 'android' ? 'sms-otp' : 'one-time-code'}
        maxLength={length}
        accessibilityLabel={`${length}-digit verification code`}
        style={styles.hidden}
        caretHidden
      />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', gap: 8, justifyContent: 'space-between' },
  cell: {
    flex: 1,
    maxWidth: 54,
    aspectRatio: 0.86,
    borderRadius: radius.md,
    borderWidth: 1.5,
    borderColor: colors.border,
    backgroundColor: colors.card,
    alignItems: 'center',
    justifyContent: 'center',
  },
  active: { borderColor: colors.cyan, borderWidth: 2 },
  filled: { borderColor: colors.navy },
  error: { borderColor: colors.error, backgroundColor: colors.errorBg },
  char: { fontFamily: font.bold, fontSize: 24, color: colors.text },
  hidden: { position: 'absolute', opacity: 0.011, width: '100%', height: '100%' },
});
