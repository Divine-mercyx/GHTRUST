import { Image } from 'expo-image';
import { StyleSheet, View } from 'react-native';

import { colors, shadow } from '@/theme/tokens';

const MARK = require('../../assets/images/logo.png');

/**
 * The GH Trust logo: the navy G and cyan rising dots on a white rounded tile, as in the
 * brand logo. Reads on light screens and on navy ones (`inverse`: no border, a soft shadow).
 * The artwork comes from scripts/make-logo.py.
 */
export function Logo({ size = 56, inverse = false }: { size?: number; inverse?: boolean }) {
  return (
    <View
      accessibilityRole="image"
      accessibilityLabel="GH Trust"
      style={[
        styles.tile,
        inverse ? shadow : styles.border,
        { width: size, height: size, borderRadius: size * 0.24, padding: size * 0.14 },
      ]}>
      <Image source={MARK} style={styles.mark} contentFit="contain" />
    </View>
  );
}

const styles = StyleSheet.create({
  tile: { backgroundColor: colors.white, alignItems: 'center', justifyContent: 'center' },
  border: { borderWidth: StyleSheet.hairlineWidth, borderColor: colors.borderStrong },
  mark: { width: '100%', height: '100%' },
});
