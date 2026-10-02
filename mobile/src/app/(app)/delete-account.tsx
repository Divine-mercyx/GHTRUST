import Ionicons from '@expo/vector-icons/Ionicons';
import { useMutation } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useRef, useState } from 'react';
import { Alert, StyleSheet, View } from 'react-native';

import { auth } from '@/api/endpoints';
import { messageFor } from '@/api/errors';
import { useSession } from '@/auth/session';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { Field } from '@/components/Field';
import { Screen } from '@/components/Screen';
import { Banner, CardSkeleton, ErrorState } from '@/components/States';
import { Text } from '@/components/Text';
import { DELETE_WORD as WORD, alreadyDeleted, blockedByServer, canConfirmDeletion, noReply } from '@/lib/accountDeletion';
import { confirm } from '@/lib/confirm';
import { useDeletionCheck } from '@/lib/queries';
import { colors, radius, space } from '@/theme/tokens';


/**
 * Delete account: explain what happens (and anything stopping it), then the sign-in PIN,
 * typing DELETE, and a last "are you sure". On success the app forgets this phone and
 * returns to the welcome screen.
 */
export default function DeleteAccount() {
  const check = useDeletionCheck();
  const { signOut } = useSession();
  const [step, setStep] = useState<'explain' | 'confirm'>('explain');
  const [pin, setPin] = useState('');
  const [word, setWord] = useState('');
  // An attempt failed without a reply (timeout, lost connection): it may have gone through.
  const uncertainRef = useRef(false);

  const finish = (title: string, message: string) => {
    Alert.alert(title, message);
    void signOut({ forget: true });
  };

  const remove = useMutation({
    // The flag says whether an earlier attempt's outcome is unknown.
    mutationFn: (_afterUncertain: boolean) => auth.deleteAccount(pin),
    onSuccess: () =>
      finish('Your account has been deleted', 'You have been signed out. Thank you for banking with GH Trust.'),
    onError: (e, afterUncertain) => {
      // Already deleted by an earlier attempt whose reply never arrived: the session is gone.
      if (alreadyDeleted(e, afterUncertain)) {
        finish('Your account has been deleted', 'You have been signed out.');
        return;
      }
      if (noReply(e)) uncertainRef.current = true;
      if (blockedByServer(e)) void check.refetch(); // something opened since the check
    },
  });

  if (check.isPending) {
    return (
      <Screen edges={['bottom']}>
        <CardSkeleton lines={5} />
      </Screen>
    );
  }
  if (check.isError || !check.data) {
    return (
      <Screen edges={['bottom']}>
        <ErrorState error={check.error} onRetry={() => check.refetch()} />
      </Screen>
    );
  }

  const c = check.data;
  const ready = canConfirmDeletion(pin, word);

  if (step === 'explain') {
    return (
      <Screen
        edges={['bottom']}
        onRefresh={() => check.refetch()}
        refreshing={check.isRefetching}
        footer={
          <View style={{ gap: space.sm }}>
            <Button
              title="Continue"
              variant="danger"
              disabled={!c.can_delete}
              onPress={() => setStep('confirm')}
            />
            <Button title="Keep my account" variant="ghost" onPress={() => router.back()} />
          </View>
        }>
        <View style={styles.hero}>
          <View style={styles.heroIcon}>
            <Ionicons name="trash-outline" size={28} color={colors.error} />
          </View>
          <Text variant="title" align="center">
            Delete your account
          </Text>
          <Text muted align="center">
            Deleting your account is permanent and can't be undone. You'll be signed out on every phone.
          </Text>
        </View>

        {c.blockers.map((b) => (
          <Banner key={b.code} tone="warning" message={b.message} />
        ))}

        <Card style={{ gap: space.sm }}>
          <Text variant="heading">What we delete</Text>
          {c.will_delete.map((line) => (
            <Bullet key={line} icon="close-circle" color={colors.error} text={line} />
          ))}
        </Card>

        <Card style={{ gap: space.sm }}>
          <Text variant="heading">What we have to keep</Text>
          {c.will_keep.map((line) => (
            <Bullet key={line} icon="lock-closed" color={colors.textFaint} text={line} />
          ))}
          <Text variant="small" muted>
            The law requires us to keep some financial records for a period after you leave. We keep only what
            links them to you. Our Privacy Policy explains this.
          </Text>
        </Card>
      </Screen>
    );
  }

  return (
    <Screen
      edges={['bottom']}
      footer={
        <View style={{ gap: space.sm }}>
          {remove.error ? <Banner message={messageFor(remove.error)} /> : null}
          <Button
            title="Delete my account"
            variant="danger"
            icon="trash-outline"
            loading={remove.isPending}
            disabled={!ready || remove.isPending}
            onPress={() =>
              confirm(
                'Delete your account?',
                'This permanently deletes your GH Trust account. You can\'t undo it.',
                'Delete',
                () => remove.mutate(uncertainRef.current),
              )
            }
          />
          <Button title="Cancel" variant="ghost" disabled={remove.isPending} onPress={() => router.back()} />
        </View>
      }>
      <Text variant="title">Confirm it's you</Text>
      <Text muted>Enter your 6-digit sign-in PIN, then type {WORD} to confirm.</Text>
      <Field
        label="Sign-in PIN"
        value={pin}
        onChangeText={(v) => setPin(v.replace(/\D/g, '').slice(0, 6))}
        keyboardType="number-pad"
        secureTextEntry
        maxLength={6}
        autoComplete="off"
        textContentType="oneTimeCode"
        editable={!remove.isPending}
      />
      <Field
        label={`Type ${WORD}`}
        value={word}
        onChangeText={setWord}
        autoCapitalize="characters"
        autoCorrect={false}
        editable={!remove.isPending}
      />
    </Screen>
  );
}

function Bullet({ icon, color, text }: { icon: keyof typeof Ionicons.glyphMap; color: string; text: string }) {
  return (
    <View style={styles.bullet}>
      <Ionicons name={icon} size={16} color={color} style={{ marginTop: 2 }} />
      <Text variant="small" style={{ flex: 1, lineHeight: 20 }}>
        {text}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  hero: { alignItems: 'center', gap: space.sm, paddingVertical: space.md },
  heroIcon: {
    width: 64,
    height: 64,
    borderRadius: radius.pill,
    backgroundColor: colors.errorBg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  bullet: { flexDirection: 'row', gap: space.sm, alignItems: 'flex-start' },
});
