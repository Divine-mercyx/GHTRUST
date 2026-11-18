import Ionicons from '@expo/vector-icons/Ionicons';
import { CameraView, useCameraPermissions } from 'expo-camera';
import * as Haptics from 'expo-haptics';
import { router, Stack } from 'expo-router';
import { useEffect, useEffectEvent, useRef, useState } from 'react';
import { ActivityIndicator, Linking, Platform, Pressable, StyleSheet, useWindowDimensions, View } from 'react-native';
import Animated, {
  FadeIn,
  FadeInDown,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withSequence,
  withTiming,
} from 'react-native-reanimated';
import { SafeAreaView } from 'react-native-safe-area-context';

import { auth } from '@/api/endpoints';
import { ApiError, messageFor, waitPhrase } from '@/api/errors';
import { deviceInfo } from '@/auth/device';
import { pendingSelfie } from '@/auth/pending';
import { useSession } from '@/auth/session';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { Banner } from '@/components/States';
import { Text } from '@/components/Text';
import { captureFrame, LIVENESS_STEPS, SETTLE_MS, type Frame } from '@/features/selfie';
import { colors, font, space } from '@/theme/tokens';

const TIPS: { icon: keyof typeof Ionicons.glyphMap; text: string }[] = [
  { icon: 'sunny-outline', text: 'Face a window or light, not behind you' },
  {
    icon: 'glasses-outline',
    text: 'Take off glasses, caps and face coverings',
  },
  {
    icon: 'happy-outline',
    text: 'Hold the phone at eye level and follow the prompts',
  },
];

type Stage = 'intro' | 'live' | 'checking';

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Last step of opening an account: a live face check. The customer follows prompts in
 * front of the camera while frames are captured automatically (there is no photo to
 * snap or pick). Dojah checks it's a live person, then matches the face to the BVN
 * photo, so only the BVN's owner can open an account with it.
 */
export default function LiveFaceCheck() {
  const { signIn } = useSession();
  const pending = pendingSelfie.get();
  const [permission, requestPermission] = useCameraPermissions();
  const [stage, setStage] = useState<Stage>('intro');
  const [error, setError] = useState<string | null>(null);
  const [left, setLeft] = useState(pending?.attemptsLeft ?? 0);
  const [ended, setEnded] = useState<'cooldown' | 'expired' | null>(null);
  const [cooldownSeconds, setCooldownSeconds] = useState(0);

  useEffect(() => {
    if (!pending) router.replace('/register');
  }, [pending]);
  if (!pending) return null;

  const start = async () => {
    setError(null);
    const granted = permission?.granted || (await requestPermission()).granted;
    if (granted) setStage('live');
  };

  const submit = async (frames: Frame[]) => {
    setStage('checking');
    const main = frames[frames.length - 1];
    try {
      const tokens = await auth.registrationSelfie(
        pending.token,
        main.base64,
        frames.slice(0, -1).map((f) => f.base64),
        await deviceInfo(),
      );
      pendingSelfie.clear();
      await signIn(tokens); // the app then asks them to create their PINs
    } catch (err) {
      failed(err);
    }
  };

  const failed = (err: unknown) => {
    setStage('intro');
    if (err instanceof ApiError && err.code === 'SELFIE_COOLDOWN') {
      setCooldownSeconds(err.waitSeconds ?? 3600);
      setEnded('cooldown');
    } else if (err instanceof ApiError && err.code === 'REGISTRATION_EXPIRED') {
      setEnded('expired');
    } else {
      if (err instanceof ApiError && err.attemptsLeft !== undefined) setLeft(err.attemptsLeft);
      setError(messageFor(err, err instanceof Error ? err.message : undefined));
    }
  };

  if (ended) {
    return (
      <Screen
        edges={['bottom']}
        scroll={false}
        footer={
          <Button
            title={ended === 'expired' ? 'Start again' : 'Back to start'}
            onPress={() => {
              pendingSelfie.clear();
              router.replace(ended === 'expired' ? '/register' : '/welcome');
            }}
          />
        }>
        <View style={styles.center}>
          <View style={[styles.badge, { backgroundColor: colors.warningBg }]}>
            <Ionicons
              name={ended === 'expired' ? 'time-outline' : 'hourglass-outline'}
              size={34}
              color={colors.warning}
            />
          </View>
          <Text variant="title" align="center">
            {ended === 'expired' ? 'Sign-up expired' : 'Take a short break'}
          </Text>
          <Text muted align="center">
            {ended === 'expired'
              ? 'For your security, this sign-up timed out. Start again with your BVN.'
              : `We couldn't confirm your face after several tries. For your security, you can start again with your BVN ${waitPhrase(cooldownSeconds)}. Use good light and follow the prompts on screen.`}
          </Text>
        </View>
      </Screen>
    );
  }

  if (stage === 'live') {
    return (
      <>
        <Stack.Screen options={{ headerShown: false }} />
        <LiveCapture onCaptured={submit} onError={failed} onCancel={() => setStage('intro')} />
      </>
    );
  }

  if (stage === 'checking') {
    return (
      <View style={styles.checking}>
        <Stack.Screen options={{ headerShown: false }} />
        <ActivityIndicator size="large" color={colors.white} />
        <Text variant="heading" color={colors.white} align="center">
          Checking it's really you…
        </Text>
        <Text color="rgba(255,255,255,0.75)" align="center">
          This takes a few seconds. Keep the app open.
        </Text>
      </View>
    );
  }

  const cameraBlocked = permission && !permission.granted && !permission.canAskAgain;
  return (
    <>
      <Stack.Screen options={{ headerShown: true }} />
      <Screen
        edges={['bottom']}
        footer={
          cameraBlocked ? (
            <Button title="Open Settings" icon="settings-outline" onPress={() => Linking.openSettings()} />
          ) : (
            <Button title={error ? 'Try again' : 'Start face check'} icon="scan-outline" onPress={start} />
          )
        }>
        <Animated.View entering={FadeInDown.duration(350)} style={{ gap: space.xs }}>
          <Text variant="caption" color={colors.cyanDeep}>
            LAST STEP
          </Text>
          <Text variant="title">Quick face check, {pending.firstName}</Text>
          <Text muted>
            We'll check it's really you on the live camera and match your face to your BVN photo, so no one else can
            open an account in your name.
          </Text>
        </Animated.View>

        {error ? <Banner message={error} /> : null}
        {cameraBlocked ? (
          <Banner tone="warning" message="Camera access is off. Allow it in Settings to continue." />
        ) : null}

        <Animated.View entering={FadeIn.duration(400)} style={styles.frameWrap}>
          <View style={styles.frame}>
            <Ionicons name="scan-outline" size={96} color={colors.borderStrong} />
          </View>
          {left > 0 && left < (pending.attemptsLeft ?? 3) ? (
            <Text variant="small" color={colors.warning} align="center">
              {left} {left === 1 ? 'try' : 'tries'} left
            </Text>
          ) : null}
        </Animated.View>

        <Card style={styles.tips}>
          {TIPS.map((t) => (
            <View key={t.icon} style={styles.tip}>
              <Ionicons name={t.icon} size={18} color={colors.cyanDeep} />
              <Text variant="small" style={{ flex: 1 }}>
                {t.text}
              </Text>
            </View>
          ))}
        </Card>
        <Text variant="small" muted align="center">
          Only used to confirm it's you. Nothing is posted anywhere.
        </Text>
      </Screen>
    </>
  );
}

const OVAL_W = 280; // testers asked for a bigger oval (was 250 × 330)
const OVAL_H = 370;
const MASK = 900; // thick border around the oval darkens everything outside it

/** Full-screen front camera with a face oval; prompts run and frames are captured automatically. */
function LiveCapture({
  onCaptured,
  onError,
  onCancel,
}: {
  onCaptured: (frames: Frame[]) => void;
  onError: (err: unknown) => void;
  onCancel: () => void;
}) {
  const camera = useRef<CameraView>(null);
  const { height } = useWindowDimensions();
  const [ready, setReady] = useState(false);
  const [step, setStep] = useState(-1); // -1: getting into position
  const [flash, setFlash] = useState(0);
  const pulse = useSharedValue(1);
  // Stable wrappers: the capture must not restart if the screen above re-renders.
  const captured = useEffectEvent((frames: Frame[]) => onCaptured(frames));
  const errored = useEffectEvent((err: unknown) => onError(err));

  useEffect(() => {
    pulse.value = withRepeat(withSequence(withTiming(1.03, { duration: 700 }), withTiming(1, { duration: 700 })), -1);
  }, [pulse]);

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    (async () => {
      try {
        await wait(SETTLE_MS);
        const frames: Frame[] = [];
        for (let i = 0; i < LIVENESS_STEPS.length; i++) {
          if (cancelled) return;
          setStep(i);
          await wait(LIVENESS_STEPS[i].holdMs);
          if (cancelled || !camera.current) return;
          frames.push(await captureFrame(camera.current));
          setFlash((n) => n + 1);
          if (Platform.OS !== 'web') Haptics.selectionAsync().catch(() => undefined);
        }
        if (!cancelled) captured(frames);
      } catch (err) {
        if (!cancelled) errored(err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ready]);

  const ring = useAnimatedStyle(() => ({
    transform: [{ scale: pulse.value }],
  }));
  const current = step >= 0 ? LIVENESS_STEPS[step] : null;
  const ovalTop = Math.max(120, height * 0.42 - OVAL_H / 2);

  return (
    <View style={styles.live}>
      <CameraView
        ref={camera}
        style={StyleSheet.absoluteFill}
        facing="front"
        mode="picture"
        animateShutter={false}
        onCameraReady={() => setReady(true)}
        onMountError={(e) => onError(new Error(e.message || "We couldn't start the camera."))}
      />
      <View pointerEvents="none" style={[styles.mask, { top: ovalTop - MASK }]} />
      <Animated.View
        pointerEvents="none"
        style={[
          styles.ring,
          {
            top: ovalTop,
            borderColor: current ? colors.cyan : 'rgba(255,255,255,0.9)',
          },
          ring,
        ]}
      />

      <SafeAreaView edges={['top']} style={styles.topBar}>
        <Pressable accessibilityRole="button" accessibilityLabel="Cancel face check" onPress={onCancel} hitSlop={12}>
          <Ionicons name="close" size={28} color={colors.white} />
        </Pressable>
        <View style={styles.live_badge}>
          <View style={styles.dot} />
          <Text variant="small" color={colors.white} style={{ fontFamily: font.bold }}>
            LIVE
          </Text>
        </View>
        <View style={{ width: 28 }} />
      </SafeAreaView>

      <SafeAreaView edges={['bottom']} style={styles.bottom}>
        <Animated.View key={`${step}`} entering={FadeInDown.duration(250)} style={{ gap: space.xxs }}>
          <Text variant="title" color={colors.white} align="center" accessibilityLiveRegion="polite">
            {!ready ? 'Starting camera…' : current ? current.prompt : 'Position your face in the oval'}
          </Text>
          <Text color="rgba(255,255,255,0.8)" align="center">
            {current ? current.hint : 'Hold the phone at eye level'}
          </Text>
        </Animated.View>
        <View style={styles.steps}>
          {LIVENESS_STEPS.map((s, i) => (
            <View
              key={s.key}
              style={[styles.stepDot, i < flash && styles.stepDone, i === step && i >= flash && styles.stepActive]}
            />
          ))}
        </View>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: space.sm,
  },
  badge: {
    width: 72,
    height: 72,
    borderRadius: 36,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: space.sm,
  },
  frameWrap: { alignItems: 'center', gap: space.sm, paddingVertical: space.sm },
  frame: {
    width: 200,
    height: 240,
    borderRadius: 100,
    borderWidth: 3,
    borderColor: colors.cyan,
    borderStyle: 'dashed',
    backgroundColor: colors.card,
    alignItems: 'center',
    justifyContent: 'center',
  },
  tips: { gap: space.sm },
  tip: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  checking: {
    flex: 1,
    backgroundColor: colors.navy,
    alignItems: 'center',
    justifyContent: 'center',
    gap: space.md,
    padding: space.xl,
  },
  live: { flex: 1, backgroundColor: '#000' },
  mask: {
    position: 'absolute',
    alignSelf: 'center',
    width: OVAL_W + MASK * 2,
    height: OVAL_H + MASK * 2,
    borderWidth: MASK,
    borderRadius: MASK + OVAL_W / 2,
    borderColor: 'rgba(8, 16, 40, 0.72)',
  },
  ring: {
    position: 'absolute',
    alignSelf: 'center',
    width: OVAL_W,
    height: OVAL_H,
    borderRadius: OVAL_W / 2,
    borderWidth: 4,
  },
  topBar: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: space.xl,
    paddingTop: space.sm,
  },
  live_badge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.xxs,
    backgroundColor: 'rgba(0,0,0,0.35)',
    paddingHorizontal: space.sm,
    paddingVertical: space.xxs,
    borderRadius: 999,
  },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.error },
  bottom: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
    paddingHorizontal: space.xl,
    paddingBottom: space.xl,
    gap: space.lg,
  },
  steps: { flexDirection: 'row', justifyContent: 'center', gap: space.xs },
  stepDot: {
    width: 28,
    height: 6,
    borderRadius: 3,
    backgroundColor: 'rgba(255,255,255,0.3)',
  },
  stepActive: { backgroundColor: colors.cyan },
  stepDone: { backgroundColor: colors.success },
});
