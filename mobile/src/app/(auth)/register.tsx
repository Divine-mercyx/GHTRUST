import Ionicons from '@expo/vector-icons/Ionicons';
import { useMutation } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { auth } from '@/api/endpoints';
import { ApiError, messageFor } from '@/api/errors';
import { pendingOtp, testModeCode } from '@/auth/pending';
import { Button } from '@/components/Button';
import { Field } from '@/components/Field';
import { Screen } from '@/components/Screen';
import { Banner } from '@/components/States';
import { Text } from '@/components/Text';
import { digits } from '@/lib/format';
import { colors, radius, space } from '@/theme/tokens';

export default function Register() {
  const [bvn, setBvn] = useState('');
  const [touched, setTouched] = useState(false);
  const valid = bvn.length === 11;

  const submit = useMutation({
    mutationFn: () => auth.registerBvn(bvn),
    onSuccess: (res) => {
      pendingOtp.set({
        mode: 'register',
        bvn,
        phoneMasked: res.phone_masked,
        expiresIn: res.expires_in,
        devCode: testModeCode(res.dev_code),
      });
      router.push('/verify');
    },
  });

  const error = submit.error;
  const exists = error instanceof ApiError && error.code === 'ACCOUNT_EXISTS';

  return (
    <Screen
      edges={['bottom']}
      footer={
        <Button
          title="Continue"
          disabled={!valid}
          loading={submit.isPending}
          onPress={() => {
            setTouched(true);
            if (valid) submit.mutate();
          }}
        />
      }>
      <Text variant="title">Create your account</Text>
      <Text muted>
        Enter your Bank Verification Number. We'll send a code to the phone number registered with your BVN.
      </Text>

      {error ? (
        <View style={{ gap: space.xs }}>
          <Banner message={messageFor(error)} />
          {exists ? <Button title="Sign in instead" variant="ghost" onPress={() => router.replace('/sign-in')} /> : null}
        </View>
      ) : null}

      <Field
        label="BVN"
        value={bvn}
        onChangeText={(t) => setBvn(digits(t).slice(0, 11))}
        onBlur={() => setTouched(true)}
        keyboardType="number-pad"
        maxLength={11}
        placeholder="11-digit BVN"
        autoFocus
        returnKeyType="done"
        onSubmitEditing={() => valid && submit.mutate()}
        error={touched && bvn.length > 0 && !valid ? 'Your BVN has 11 digits.' : null}
        hint="Dial *565*0# on your registered line to get your BVN."
      />

      <View style={styles.note}>
        <Ionicons name="lock-closed" size={16} color={colors.cyanDeep} />
        <Text variant="small" muted style={{ flex: 1 }}>
          Your BVN is only used to verify your identity. It doesn't give GH Trust access to your other bank accounts.
        </Text>
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  note: {
    flexDirection: 'row',
    gap: space.xs,
    padding: space.md,
    borderRadius: radius.md,
    backgroundColor: colors.mint,
  },
});
