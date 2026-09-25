import { useMutation } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useState } from 'react';

import { auth } from '@/api/endpoints';
import { messageFor } from '@/api/errors';
import { pendingOtp, testModeCode } from '@/auth/pending';
import { Button } from '@/components/Button';
import { Field } from '@/components/Field';
import { Screen } from '@/components/Screen';
import { Banner } from '@/components/States';
import { Text } from '@/components/Text';
import { digits } from '@/lib/format';

/** Accepts 0803…, 803… or 234803…; returns the national number or null. */
function nationalNumber(raw: string): string | null {
  let d = digits(raw);
  if (d.startsWith('234')) d = d.slice(3);
  if (d.startsWith('0')) d = d.slice(1);
  return /^[789]\d{9}$/.test(d) ? d : null;
}

export default function SignIn() {
  const [phone, setPhone] = useState('');
  const [touched, setTouched] = useState(false);
  const national = nationalNumber(phone);

  const submit = useMutation({
    mutationFn: () => auth.requestLogin(`0${national}`),
    onSuccess: (res) => {
      pendingOtp.set({
        mode: 'login',
        phone: `0${national}`,
        phoneMasked: res.phone_masked,
        expiresIn: res.expires_in,
        devCode: testModeCode(res.dev_code),
      });
      router.push('/verify');
    },
  });

  return (
    <Screen
      edges={['bottom']}
      footer={
        <Button
          title="Send code"
          disabled={!national}
          loading={submit.isPending}
          onPress={() => {
            setTouched(true);
            if (national) submit.mutate();
          }}
        />
      }>
      <Text variant="title">Welcome back</Text>
      <Text muted>Enter the phone number on your GH Trust account. We'll text you a sign-in code.</Text>

      {submit.error ? <Banner message={messageFor(submit.error)} /> : null}

      <Field
        label="Phone number"
        prefix="+234"
        value={phone}
        onChangeText={(t) => setPhone(digits(t).slice(0, 14))}
        onBlur={() => setTouched(true)}
        keyboardType="phone-pad"
        textContentType="telephoneNumber"
        autoComplete="tel"
        placeholder="803 123 4567"
        autoFocus
        returnKeyType="done"
        onSubmitEditing={() => national && submit.mutate()}
        error={touched && phone.length > 0 && !national ? 'Enter a valid Nigerian mobile number.' : null}
      />
    </Screen>
  );
}
