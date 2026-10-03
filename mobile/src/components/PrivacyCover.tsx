import { useEffect, useState } from 'react';
import { AppState, StyleSheet, View } from 'react-native';

import { colors } from '@/theme/tokens';

import { Logo } from './Logo';

/**
 * Covers the screen whenever the app isn't in front, so the app switcher shows the GH Trust
 * mark instead of balances and loans. iOS takes its switcher snapshot while the app is
 * "inactive", so this reliably hides it there. Android may snapshot before React draws the
 * cover; hiding it there fully needs FLAG_SECURE (a native change, which also blocks
 * screenshots).
 */
export function PrivacyCover() {
  const [hidden, setHidden] = useState(AppState.currentState !== 'active');

  useEffect(() => {
    const sub = AppState.addEventListener('change', (state) => setHidden(state !== 'active'));
    return () => sub.remove();
  }, []);

  if (!hidden) return null;
  return (
    <View style={styles.cover} pointerEvents="none" accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      <Logo size={72} inverse />
    </View>
  );
}

const styles = StyleSheet.create({
  cover: {
    position: 'absolute',
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    backgroundColor: colors.navy,
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1000,
    elevation: 1000,
  },
});
