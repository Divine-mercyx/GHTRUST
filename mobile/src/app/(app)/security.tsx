import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { Linking, Switch } from 'react-native';

import { security } from '@/api/endpoints';
import { messageFor } from '@/api/errors';
import { biometricName } from '@/auth/lock';
import { LOCK_CHOICES } from '@/auth/lockPolicy';
import { useSession } from '@/auth/session';
import { Card, Row, SectionHeader } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { Banner } from '@/components/States';
import { Text } from '@/components/Text';
import { dateTime } from '@/lib/format';
import { disablePush, enablePush, pushState, type PushState } from '@/lib/push';
import { useMe } from '@/lib/queries';
import { colors, space } from '@/theme/tokens';

export default function Security() {
  const me = useMe();
  const { biometric, biometricAvailable, setBiometric, lockAfterMs, setLockAfter } = useSession();
  const [error, setError] = useState<string | null>(null);
  const [openedAt] = useState(() => Date.now());
  const [push, setPush] = useState<PushState | null>(null);

  useEffect(() => {
    pushState()
      .then(setPush)
      .catch(() => setPush('unsupported'));
  }, []);

  const togglePush = async (on: boolean) => {
    setError(null);
    setPush(on ? 'on' : 'off'); // move the switch straight away
    try {
      if (on) setPush(await enablePush());
      else await disablePush();
    } catch (err) {
      setError(messageFor(err));
      setPush(await pushState().catch(() => 'off' as const));
    }
  };
  const p = me.data;
  const hold = p?.transfers_blocked_until ? new Date(p.transfers_blocked_until) : null;
  const onHold = hold && hold.getTime() > openedAt;

  const toggleBiometric = async (on: boolean) => {
    setError(null);
    if (on) return router.push('/pin/enable-biometric');
    try {
      await security.setBiometrics(false);
    } catch (err) {
      // Turning it off locally is what matters; the server flag only widens what a biometric can approve.
      setError(messageFor(err));
    }
    await setBiometric(false);
  };

  return (
    <Screen edges={['bottom']}>
      {onHold ? (
        <Banner
          tone="warning"
          message={`You signed in without your old phone, so money can't leave your account until ${dateTime(hold!.toISOString())}.`}
        />
      ) : null}
      {error ? <Banner message={error} /> : null}

      <SectionHeader title="Sign-in PIN" />
      <Card style={{ paddingVertical: space.xs }}>
        <Row
          icon="keypad-outline"
          title="Change sign-in PIN"
          subtitle="The 6 digits that open GH Trust"
          onPress={() => router.push('/pin/change-login')}
          last={!biometricAvailable}
        />
        {biometricAvailable ? (
          <Row
            icon={biometricAvailable === 'face' ? 'scan-outline' : 'finger-print'}
            title={`Unlock with ${biometricName(biometricAvailable)}`}
            subtitle="Instead of typing your PIN on this phone"
            trailing={
              <Switch
                value={!!biometric}
                onValueChange={toggleBiometric}
                trackColor={{ true: colors.navy, false: colors.borderStrong }}
                accessibilityLabel={`Unlock with ${biometricName(biometricAvailable)}`}
              />
            }
            last
          />
        ) : null}
      </Card>

      <SectionHeader title="Lock app" />
      <Card style={{ paddingVertical: space.xs }}>
        {LOCK_CHOICES.map((c, i) => {
          const selected = c.ms === lockAfterMs;
          return (
            <Row
              key={c.ms}
              icon={c.ms === 0 ? 'lock-closed-outline' : 'time-outline'}
              title={c.label}
              subtitle={c.hint}
              onPress={selected ? undefined : () => void setLockAfter(c.ms).catch(() => setError("We couldn't save that. Try again."))}
              trailing={
                selected ? (
                  <Ionicons name="checkmark-circle" size={22} color={colors.cyanDeep} accessibilityLabel="Selected" />
                ) : (
                  <Ionicons name="ellipse-outline" size={22} color={colors.borderStrong} />
                )
              }
              last={i === LOCK_CHOICES.length - 1}
            />
          );
        })}
      </Card>
      <Text variant="small" muted style={{ paddingHorizontal: space.xs }}>
        When you leave GH Trust for this long, you'll need your sign-in PIN
        {biometric ? ` or ${biometricName(biometric)}` : ''} to get back in. The app also locks if it's open but untouched for
        this long (at least 5 minutes).
      </Text>

      <SectionHeader title="Transaction PIN" />
      <Card style={{ paddingVertical: space.xs }}>
        {p?.transaction_pin_set ? (
          <>
            <Row
              icon="card-outline"
              title="Change transaction PIN"
              subtitle="The 4 digits that approve payments"
              onPress={() => router.push('/pin/change-transaction')}
            />
            <Row
              icon="help-circle-outline"
              title="Forgot transaction PIN"
              subtitle="Set a new one with your sign-in PIN"
              onPress={() => router.push('/pin/reset-transaction')}
              last
            />
          </>
        ) : (
          <Row
            icon="card-outline"
            title="Create transaction PIN"
            subtitle="Needed before money can leave your account"
            onPress={() => router.push('/pin/set-transaction')}
            last
          />
        )}
      </Card>

      {push && push !== 'unsupported' ? (
        <>
          <SectionHeader title="Notifications" />
          <Card style={{ paddingVertical: space.xs }}>
            {push === 'blocked' ? (
              <Row
                icon="notifications-off-outline"
                title="Notifications are off"
                subtitle="Allow them for GH Trust in your phone's settings"
                onPress={() => Linking.openSettings()}
                last
              />
            ) : (
              <Row
                icon="notifications-outline"
                title="Push notifications"
                subtitle="Payments, loan updates, reminders and sign-in alerts"
                trailing={
                  <Switch
                    value={push === 'on'}
                    onValueChange={togglePush}
                    trackColor={{ true: colors.navy, false: colors.borderStrong }}
                    accessibilityLabel="Push notifications"
                  />
                }
                last
              />
            )}
          </Card>
        </>
      ) : null}

      <SectionHeader title="Phones" />
      <Card style={{ paddingVertical: space.xs }}>
        <Row
          icon="phone-portrait-outline"
          title="Signed-in devices"
          subtitle="See and remove phones"
          onPress={() => router.push('/devices')}
          last
        />
      </Card>
      <Text variant="small" muted style={{ paddingHorizontal: space.xs }}>
        Signing in on a new phone needs your approval on a phone that's already signed in.
      </Text>
    </Screen>
  );
}
