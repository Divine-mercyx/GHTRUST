import { useCallback, useEffect, useRef, useState } from 'react';
import { StyleSheet } from 'react-native';
import Animated, { FadeIn } from 'react-native-reanimated';

import { unlock } from '@/auth/lock';
import { useSession } from '@/auth/session';
import { Button } from '@/components/Button';
import { Logo } from '@/components/Logo';
import { Screen } from '@/components/Screen';
import { Text } from '@/components/Text';
import { greeting } from '@/lib/format';
import { space } from '@/theme/tokens';

const LABEL = { face: 'Unlock with Face ID', fingerprint: 'Unlock with fingerprint', passcode: 'Unlock with passcode', none: 'Continue' };

export default function Unlock() {
  const { firstName, lock, unlocked, forget } = useSession();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const prompted = useRef(false);

  const attempt = useCallback(async () => {
    setBusy(true);
    try {
      if (lock === 'none' || (await unlock())) unlocked();
      else setFailed(true);
    } finally {
      setBusy(false);
    }
  }, [lock, unlocked]);

  // Prompt straight away on arrival; the button is there if it's dismissed.
  useEffect(() => {
    if (!prompted.current) {
      prompted.current = true;
      attempt();
    }
  }, [attempt]);

  return (
    <Screen
      scroll={false}
      footer={
        <>
          <Button
            title={LABEL[lock]}
            icon={lock === 'face' ? 'scan-outline' : lock === 'fingerprint' ? 'finger-print' : 'keypad-outline'}
            loading={busy}
            onPress={attempt}
          />
          <Button title={firstName ? `Not ${firstName}? Sign out` : 'Sign out'} variant="ghost" onPress={() => forget()} />
        </>
      }>
      <Animated.View entering={FadeIn.duration(400)} style={styles.center}>
        <Logo size={72} />
        <Text variant="title" align="center" style={{ marginTop: space.lg }}>
          {greeting()}
          {firstName ? `, ${firstName}` : ''}
        </Text>
        <Text muted align="center">
          {failed ? "That didn't work. Try again to unlock GH Trust." : 'Unlock to continue to your account.'}
        </Text>
      </Animated.View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: space.xs },
});
