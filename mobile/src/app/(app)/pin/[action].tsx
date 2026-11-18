import Ionicons from '@expo/vector-icons/Ionicons';
import { useQueryClient } from '@tanstack/react-query';
import { router, Stack, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { StyleSheet, View } from 'react-native';
import Animated, { ZoomIn } from 'react-native-reanimated';
import { SafeAreaView } from 'react-native-safe-area-context';

import { security } from '@/api/endpoints';
import { ApiError } from '@/api/errors';
import { biometricName, checkBiometric } from '@/auth/lock';
import { useSession } from '@/auth/session';
import { Button } from '@/components/Button';
import { PinFlow, type PinStep } from '@/components/PinFlow';
import { Text } from '@/components/Text';
import { pinReset } from '@/lib/flags';
import { keys } from '@/lib/queries';
import { colors, space } from '@/theme/tokens';

export type PinAction = 'change-login' | 'set-transaction' | 'change-transaction' | 'reset-transaction' | 'enable-biometric';

const DONE: Record<PinAction, string> = {
  'change-login': 'Sign-in PIN changed',
  'set-transaction': 'Transaction PIN created',
  'change-transaction': 'Transaction PIN changed',
  'reset-transaction': 'New transaction PIN set',
  'enable-biometric': 'Turned on',
};

/** Every PIN change in Security settings, as one screen driven by the route. */
export default function PinActionScreen() {
  const { action } = useLocalSearchParams<{ action: PinAction }>();
  const queryClient = useQueryClient();
  const { biometricAvailable, setBiometric, signOut } = useSession();
  const [done, setDone] = useState(false);
  const refreshMe = () => queryClient.invalidateQueries({ queryKey: keys.me });
  const bio = biometricAvailable ? biometricName(biometricAvailable) : 'biometrics';

  const flows: Record<PinAction, { steps: PinStep[]; onDone: (v: Record<string, string>) => Promise<void> }> = {
    'change-login': {
      steps: [
        { key: 'current', title: 'Enter your current sign-in PIN', length: 6 },
        { key: 'pin', title: 'Choose a new sign-in PIN', subtitle: '6 digits you\'ll use to open GH Trust.', length: 6, isNew: true },
        { key: 'confirm', title: 'Enter it again', length: 6, confirms: 'pin' },
      ],
      onDone: ({ current, pin }) => security.changePin(current, pin),
    },
    'set-transaction': {
      steps: [
        { key: 'pin', title: 'Create your transaction PIN', subtitle: '4 digits to approve payments.', length: 4, isNew: true },
        { key: 'confirm', title: 'Enter it again', length: 4, confirms: 'pin' },
      ],
      onDone: async ({ pin }) => {
        queryClient.setQueryData(keys.me, await security.setTransactionPin(pin));
      },
    },
    'change-transaction': {
      steps: [
        { key: 'current', title: 'Enter your current transaction PIN', length: 4 },
        { key: 'pin', title: 'Choose a new transaction PIN', length: 4, isNew: true },
        { key: 'confirm', title: 'Enter it again', length: 4, confirms: 'pin' },
      ],
      onDone: ({ current, pin }) => security.changeTransactionPin(current, pin),
    },
    'reset-transaction': {
      steps: [
        { key: 'login', title: 'Enter your sign-in PIN', subtitle: 'The 6-digit PIN you use to open GH Trust.', length: 6 },
        { key: 'pin', title: 'Choose a new transaction PIN', length: 4, isNew: true },
        { key: 'confirm', title: 'Enter it again', length: 4, confirms: 'pin' },
      ],
      onDone: ({ login, pin }) => security.resetTransactionPin(login, pin),
    },
    'enable-biometric': {
      steps: [{ key: 'pin', title: `Turn on ${bio}`, subtitle: 'Enter your sign-in PIN to confirm.', length: 6 }],
      onDone: async ({ pin }) => {
        if (!(await checkBiometric(`Turn on ${bio} for GH Trust`))) {
          throw new ApiError(0, 'BIOMETRIC_CANCELLED', `${bio} wasn't confirmed.`);
        }
        await security.setBiometrics(true, pin);
        await setBiometric(true);
      },
    },
  };
  const flow = flows[action];
  // These start by asking for the sign-in PIN; someone who doesn't know it needs a way out.
  const asksSignInPin = action === 'change-login' || action === 'enable-biometric' || action === 'reset-transaction';

  if (!flow) return null;

  if (done) {
    return (
      <SafeAreaView style={styles.fill} edges={['bottom']}>
        <Stack.Screen options={{ headerShown: false }} />
        <View style={styles.done}>
          <Animated.View entering={ZoomIn.springify()} style={styles.tick}>
            <Ionicons name="checkmark" size={40} color={colors.white} />
          </Animated.View>
          <Text variant="title" align="center">
            {DONE[action]}
          </Text>
        </View>
        <Button title="Done" onPress={() => router.back()} />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.fill} edges={['bottom']}>
      <PinFlow
        steps={flow.steps}
        restartAt={(err) => {
          // Wrong current PIN: ask for it again. A weak new one: choose again.
          if (err instanceof ApiError && err.code === 'PIN_TOO_WEAK') return 'pin';
          return flow.steps[0].key;
        }}
        onDone={async (values) => {
          await flow.onDone(values);
          refreshMe();
          setDone(true);
        }}
      />
      {asksSignInPin ? (
        <Button
          title="Forgot sign-in PIN?"
          variant="ghost"
          size="sm"
          onPress={async () => {
            // Prove it's you with an SMS code and your BVN, then choose a new PIN.
            pinReset.start();
            await signOut();
          }}
        />
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1, backgroundColor: colors.surface, paddingHorizontal: space.xl, paddingBottom: space.md },
  done: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: space.md },
  tick: {
    width: 84,
    height: 84,
    borderRadius: 42,
    backgroundColor: colors.success,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
