import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { StyleSheet, View } from 'react-native';
import Animated, { FadeInDown } from 'react-native-reanimated';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button } from '@/components/Button';
import { Logo } from '@/components/Logo';
import { Text } from '@/components/Text';
import { colors, radius, space } from '@/theme/tokens';

const POINTS: { icon: keyof typeof Ionicons.glyphMap; title: string; body: string }[] = [
  { icon: 'flash-outline', title: 'Apply in minutes', body: 'Business, payday, study and asset loans from your phone.' },
  { icon: 'eye-outline', title: 'Track every step', body: 'See where your application is, from review to payout.' },
  { icon: 'shield-checkmark-outline', title: 'Secure by design', body: 'BVN-verified sign-up, and your phone locks the app.' },
];

export default function Welcome() {
  return (
    <SafeAreaView style={styles.fill} edges={['top', 'bottom']}>
      <View style={styles.hero}>
        <Animated.View entering={FadeInDown.duration(500)} style={styles.brand}>
          <Logo size={64} inverse />
          <Text variant="caption" color={colors.cyan} style={{ marginTop: space.lg }}>
            GH TRUST MICROFINANCE BANK
          </Text>
          <Text variant="display" color={colors.white}>
            Finance that moves{'\n'}at your pace.
          </Text>
        </Animated.View>
        <View style={styles.points}>
          {POINTS.map((p, i) => (
            <Animated.View key={p.title} entering={FadeInDown.delay(150 + i * 90).duration(450)} style={styles.point}>
              <View style={styles.pointIcon}>
                <Ionicons name={p.icon} size={20} color={colors.cyan} />
              </View>
              <View style={{ flex: 1 }}>
                <Text variant="bodyStrong" color={colors.white}>
                  {p.title}
                </Text>
                <Text variant="small" color="rgba(255,255,255,0.7)">
                  {p.body}
                </Text>
              </View>
            </Animated.View>
          ))}
        </View>
      </View>
      <Animated.View entering={FadeInDown.delay(450).duration(450)} style={styles.actions}>
        <Button title="Create an account" onPress={() => router.push('/register')} style={styles.primary} />
        <Button
          title="I already have an account"
          variant="secondary"
          tint={colors.white}
          onPress={() => router.push('/sign-in')}
          style={styles.secondary}
        />
      </Animated.View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1, backgroundColor: colors.navy },
  hero: { flex: 1, paddingHorizontal: space.xl, justifyContent: 'center', gap: space.xxl, maxWidth: 560, width: '100%', alignSelf: 'center' },
  brand: { gap: space.xs },
  points: { gap: space.lg },
  point: { flexDirection: 'row', gap: space.md, alignItems: 'flex-start' },
  pointIcon: {
    width: 40,
    height: 40,
    borderRadius: radius.md,
    backgroundColor: 'rgba(47,164,215,0.14)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  actions: { padding: space.xl, gap: space.sm, maxWidth: 560, width: '100%', alignSelf: 'center' },
  primary: { backgroundColor: colors.cyan },
  secondary: { backgroundColor: 'transparent', borderColor: 'rgba(255,255,255,0.35)' },
});
