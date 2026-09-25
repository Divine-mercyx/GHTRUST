import { useMutation } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { auth } from '@/api/endpoints';
import { ApiError, messageFor } from '@/api/errors';
import { deviceInfo } from '@/auth/device';
import { pendingOtp, testModeCode } from '@/auth/pending';
import { useSession } from '@/auth/session';
import { Button } from '@/components/Button';
import { OtpInput } from '@/components/OtpInput';
import { Screen } from '@/components/Screen';
import { Banner } from '@/components/States';
import { Text } from '@/components/Text';
import { space } from '@/theme/tokens';

const RESEND_AFTER_S = 60;

export default function Verify() {
  const { signIn } = useSession();
  const pending = pendingOtp.get();
  // Test mode (dev build, no SMS provider yet): the code arrives with the response.
  const [otp, setOtp] = useState(pending?.devCode ?? '');
  const testMode = !!pending?.devCode;
  const [cooldown, setCooldown] = useState(RESEND_AFTER_S);
  const [notice, setNotice] = useState<string | null>(null);
  const submitted = useRef('');

  useEffect(() => {
    if (!pending) router.back();
  }, [pending]);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  const verify = useMutation({
    mutationFn: async (code: string) => {
      if (!pending) throw new Error('No pending verification');
      const device = await deviceInfo();
      return pending.mode === 'register'
        ? auth.verifyRegistration(pending.bvn, code, device)
        : auth.verifyLogin(pending.phone, code, device);
    },
    onSuccess: async (tokens) => {
      pendingOtp.clear();
      await signIn(tokens); // guard switches to the app
    },
  });

  const resend = useMutation({
    mutationFn: () => {
      if (!pending) throw new Error('No pending verification');
      return pending.mode === 'register' ? auth.resendRegistration(pending.bvn) : auth.resendLogin(pending.phone);
    },
    onSuccess: (res) => {
      setOtp(testModeCode(res.dev_code) ?? '');
      verify.reset();
      setCooldown(RESEND_AFTER_S);
      setNotice(`A new code was sent to ${res.phone_masked}.`);
    },
    onError: (err) => {
      if (err instanceof ApiError && err.retryAfter) setCooldown(err.retryAfter);
    },
  });

  // Submit automatically once all six digits are in (once per code).
  useEffect(() => {
    if (otp.length === 6 && submitted.current !== otp && !verify.isPending) {
      submitted.current = otp;
      setNotice(null);
      verify.mutate(otp);
    }
  }, [otp, verify]);

  if (!pending) return null;

  const error = verify.error ?? resend.error;
  const mustResend = error instanceof ApiError && ['OTP_EXPIRED', 'OTP_ATTEMPTS_EXCEEDED'].includes(error.code);

  return (
    <Screen
      edges={['bottom']}
      footer={
        <Button
          title="Verify"
          disabled={otp.length !== 6 || mustResend}
          loading={verify.isPending}
          onPress={() => verify.mutate(otp)}
        />
      }>
      <Text variant="title">Enter your code</Text>
      <Text muted>
        We sent a 6-digit code to <Text variant="bodyStrong">{pending.phoneMasked}</Text>. It expires in{' '}
        {Math.round(pending.expiresIn / 60)} minutes.
      </Text>

      {error ? <Banner message={messageFor(error)} /> : notice ? <Banner tone="info" message={notice} /> : null}
      {testMode && !error ? (
        <Banner tone="info" message="Test mode: text messages aren't switched on yet, so your code was filled in for you." />
      ) : null}

      <View style={styles.otp}>
        <OtpInput
          value={otp}
          onChange={(v) => {
            setOtp(v);
            if (verify.isError) verify.reset();
          }}
          error={verify.isError}
        />
      </View>

      <View style={styles.resend}>
        {cooldown > 0 ? (
          <Text variant="small" muted>
            Didn't get it? Resend in 0:{String(cooldown).padStart(2, '0')}
          </Text>
        ) : (
          <Button title="Resend code" variant="ghost" size="sm" loading={resend.isPending} onPress={() => resend.mutate()} />
        )}
      </View>

      {pending.mode === 'login' ? (
        // For privacy the server answers the same whether or not the number has an
        // account, so offer the way forward for someone who is new.
        <View style={styles.resend}>
          <Button
            title="No account with this number? Create one"
            variant="ghost"
            size="sm"
            onPress={() => {
              pendingOtp.clear();
              router.replace('/register');
            }}
          />
        </View>
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  otp: { marginTop: space.sm },
  resend: { alignItems: 'center', minHeight: 44, justifyContent: 'center' },
});
