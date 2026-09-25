import { StyleSheet, View } from 'react-native';

import { colors, font } from '@/theme/tokens';

import { Text } from './Text';

/** Typographic mark until the brand logo asset is supplied. */
export function Logo({ size = 56, inverse = false }: { size?: number; inverse?: boolean }) {
  return (
    <View
      accessibilityRole="image"
      accessibilityLabel="GH Trust"
      style={[
        styles.mark,
        {
          width: size,
          height: size,
          borderRadius: size * 0.3,
          backgroundColor: inverse ? colors.white : colors.navy,
        },
      ]}>
      <Text style={{ fontFamily: font.extrabold, fontSize: size * 0.38, color: inverse ? colors.navy : colors.white }}>
        GH
      </Text>
      <View style={[styles.dot, { width: size * 0.16, height: size * 0.16, borderRadius: size * 0.08 }]} />
    </View>
  );
}

const styles = StyleSheet.create({
  mark: { alignItems: 'center', justifyContent: 'center' },
  dot: { position: 'absolute', right: '16%', top: '16%', backgroundColor: colors.cyan },
});
