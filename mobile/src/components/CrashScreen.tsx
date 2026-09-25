import type { ErrorBoundaryProps } from 'expo-router';
import { useEffect } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { hideSplash } from '@/lib/splash';
import { colors, HIT, radius, space } from '@/theme/tokens';

/**
 * Last-resort screen for a render error anywhere below the root layout.
 * Self-contained on purpose: it may render before fonts, the query client or
 * the session exist, so it uses system fonts and no app providers.
 */
export function CrashScreen({ error, retry }: ErrorBoundaryProps) {
  useEffect(() => {
    hideSplash(); // a crash during start-up must not leave the splash stuck
    if (__DEV__) console.log('[app] screen crashed', error); // terminal only
  }, [error]);

  return (
    <SafeAreaView style={styles.fill}>
      <View style={styles.body}>
        <Text style={styles.title}>Something went wrong</Text>
        <Text style={styles.text}>
          The app hit an unexpected problem. Your account and money are safe. Try again, and if it keeps happening,
          restart the app.
        </Text>
      </View>
      <Pressable accessibilityRole="button" onPress={retry} style={({ pressed }) => [styles.button, pressed && { opacity: 0.85 }]}>
        <Text style={styles.buttonText}>Try again</Text>
      </Pressable>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1, backgroundColor: colors.surface, padding: space.xl, justifyContent: 'space-between' },
  body: { flex: 1, justifyContent: 'center', gap: space.sm },
  title: { fontSize: 22, fontWeight: '700', color: colors.navy },
  text: { fontSize: 15, lineHeight: 22, color: colors.textMuted },
  button: {
    minHeight: HIT + 4,
    borderRadius: radius.md,
    backgroundColor: colors.navy,
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonText: { color: colors.white, fontSize: 16, fontWeight: '600' },
});
