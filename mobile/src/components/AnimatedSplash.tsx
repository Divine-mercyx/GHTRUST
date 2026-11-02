/**
 * Branded start-up animation, drawn over the app while it boots.
 *
 * Its first frame matches the native splash (navy, the logo on a white tile in the centre;
 * both from scripts/make-logo.py), so the native splash can fade out underneath with no
 * visible jump. Then: the tile settles with a ripple, rises and the wordmark writes itself in, and
 * the whole thing lifts away once the app is ready and the intro has played.
 */
import { StatusBar } from 'expo-status-bar';
import { useEffect, useState } from 'react';
import { Image } from 'expo-image';
import { StyleSheet, View } from 'react-native';
import Animated, {
  Easing,
  interpolate,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withDelay,
  withRepeat,
  withSequence,
  withSpring,
  withTiming,
  type SharedValue,
} from 'react-native-reanimated';
import { scheduleOnRN } from 'react-native-worklets';

import { colors, font } from '@/theme/tokens';

const TILE = 96; // same width as the native splash image (app.json → imageWidth)
const MARK = require('../../assets/images/logo.png');
const WORDMARK = 'GH Trust';
const TAGLINE = 'SECURE TODAY. GROW TOMORROW.';
// Heights below the tile: gap, wordmark, gap, tagline, gap, progress line.
const BELOW = 24 + 40 + 6 + 16 + 26 + 3;
const PLAY_MS = 3200; // the intro always plays in full (plus a beat to take it in), however fast start-up is
const FAILSAFE_MS = 8000; // never hold the app behind the splash longer than this
const EASE_OUT = Easing.bezier(0.22, 1, 0.36, 1);

type Props = {
  /** The app underneath is ready to be shown. */
  ready: boolean;
  onDone: () => void;
};

export function AnimatedSplash({ ready, onDone }: Props) {
  const reduced = useReducedMotion();
  const [played, setPlayed] = useState(false);
  const [timedOut, setTimedOut] = useState(false);

  const settle = useSharedValue(1);
  const ripple = useSharedValue(0);
  const lift = useSharedValue(0);
  const word = useSharedValue(0);
  const tagline = useSharedValue(0);
  const shine = useSharedValue(0);
  const progress = useSharedValue(0);
  const drift = useSharedValue(0);
  const exit = useSharedValue(0);

  useEffect(() => {
    if (reduced) {
      lift.value = 1;
      word.value = withTiming(1, { duration: 300 });
      tagline.value = withTiming(1, { duration: 300 });
      progress.value = withTiming(1, { duration: 500 });
    } else {
      settle.value = withSequence(withTiming(0.9, { duration: 200 }), withSpring(1, { damping: 8, stiffness: 190 }));
      ripple.value = withDelay(300, withTiming(1, { duration: 1500, easing: Easing.out(Easing.cubic) }));
      lift.value = withDelay(640, withSpring(1, { damping: 15, stiffness: 110 }));
      word.value = withDelay(780, withTiming(1, { duration: 720, easing: EASE_OUT }));
      tagline.value = withDelay(1180, withTiming(1, { duration: 650, easing: EASE_OUT }));
      shine.value = withDelay(1150, withTiming(1, { duration: 700, easing: Easing.inOut(Easing.quad) }));
      progress.value = withDelay(1250, withTiming(1, { duration: PLAY_MS - 1250, easing: Easing.inOut(Easing.cubic) }));
      drift.value = withRepeat(withTiming(1, { duration: 5000, easing: Easing.inOut(Easing.sin) }), -1, true);
    }
    const play = setTimeout(() => setPlayed(true), reduced ? 1200 : PLAY_MS);
    const failsafe = setTimeout(() => setTimedOut(true), FAILSAFE_MS);
    return () => {
      clearTimeout(play);
      clearTimeout(failsafe);
    };
  }, [reduced, settle, ripple, lift, word, tagline, shine, progress, drift]);

  const leaving = (played && ready) || timedOut;
  useEffect(() => {
    if (!leaving) return;
    exit.value = withTiming(
      1,
      { duration: reduced ? 250 : 750, easing: Easing.bezier(0.32, 0.72, 0, 1) },
      (finished) => {
        if (finished) scheduleOnRN(onDone);
      },
    );
  }, [leaving, reduced, exit, onDone]);

  const backdrop = useAnimatedStyle(() => ({
    opacity: interpolate(exit.value, [0.25, 1], [1, 0], 'clamp'),
  }));
  const stage = useAnimatedStyle(() => ({
    opacity: interpolate(exit.value, [0, 0.6], [1, 0], 'clamp'),
    transform: [{ translateY: (1 - lift.value) * (BELOW / 2) - exit.value * 28 }, { scale: 1 + exit.value * 0.06 }],
  }));
  const tile = useAnimatedStyle(() => ({ transform: [{ scale: settle.value }] }));
  const shineStyle = useAnimatedStyle(() => ({
    transform: [{ translateX: interpolate(shine.value, [0, 1], [-TILE * 1.2, TILE * 1.4]) }, { rotate: '20deg' }],
  }));
  const taglineStyle = useAnimatedStyle(() => ({
    opacity: tagline.value,
    letterSpacing: interpolate(tagline.value, [0, 1], [0.5, 3.2]),
  }));
  const trackStyle = useAnimatedStyle(() => ({ opacity: interpolate(tagline.value, [0, 1], [0, 1]) }));
  const progressStyle = useAnimatedStyle(() => ({ transform: [{ scaleX: progress.value }] }));
  const glowA = useAnimatedStyle(() => ({
    transform: [{ translateX: drift.value * 30 }, { translateY: drift.value * -20 }],
  }));
  const glowB = useAnimatedStyle(() => ({
    transform: [{ translateX: drift.value * -24 }, { translateY: drift.value * 26 }],
  }));

  return (
    <Animated.View
      style={[StyleSheet.absoluteFill, styles.backdrop, { pointerEvents: leaving ? 'none' : 'auto' }, backdrop]}
      accessible
      accessibilityLabel="GH Trust is starting"
      accessibilityViewIsModal>
      <StatusBar style="light" />
      <Animated.View style={[styles.glow, styles.glowTop, glowA]} />
      <Animated.View style={[styles.glow, styles.glowBottom, glowB]} />

      <Animated.View style={[styles.stage, stage]}>
        <View style={styles.tileSlot}>
          {!reduced && (
            <>
              <Ring progress={ripple} from={0} />
              <Ring progress={ripple} from={0.22} />
              <Ring progress={ripple} from={0.44} />
            </>
          )}
          <Animated.View style={[styles.tile, tile]}>
            <Image source={MARK} style={styles.mark} contentFit="contain" />
            <Animated.View style={[styles.shine, shineStyle]} />
          </Animated.View>
        </View>

        <View style={styles.wordmark}>
          {WORDMARK.split('').map((ch, i) => (
            <Letter key={i} char={ch} index={i} count={WORDMARK.length} progress={word} />
          ))}
        </View>
        <Animated.Text style={[styles.tagline, taglineStyle]}>{TAGLINE}</Animated.Text>
        <Animated.View style={[styles.track, trackStyle]}>
          <Animated.View style={[styles.bar, progressStyle]} />
        </Animated.View>
      </Animated.View>
    </Animated.View>
  );
}

/** One wordmark letter: rises and fades in, each a beat after the one before. */
function Letter({
  char,
  index,
  count,
  progress,
}: {
  char: string;
  index: number;
  count: number;
  progress: SharedValue<number>;
}) {
  const style = useAnimatedStyle(() => {
    const span = count + 3;
    const t = interpolate(progress.value, [index / span, (index + 4) / span], [0, 1], 'clamp');
    return { opacity: t, transform: [{ translateY: (1 - t) * 16 }, { scale: 0.9 + t * 0.1 }] };
  });
  return <Animated.Text style={[styles.letter, style]}>{char === ' ' ? ' ' : char}</Animated.Text>;
}

/** A cyan ring that grows out of the tile and fades, starting `from` into the ripple. */
function Ring({ progress, from }: { progress: SharedValue<number>; from: number }) {
  const style = useAnimatedStyle(() => {
    const t = interpolate(progress.value, [from, from + 0.56], [0, 1], 'clamp');
    return {
      opacity: t === 0 ? 0 : interpolate(t, [0, 0.15, 1], [0, 0.55, 0]),
      transform: [{ scale: 1 + t * 2.6 }],
    };
  });
  return <Animated.View style={[styles.ring, style]} />;
}

const styles = StyleSheet.create({
  backdrop: {
    backgroundColor: colors.navy,
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
    zIndex: 100,
  },
  glow: { position: 'absolute', width: 420, height: 420, borderRadius: 210 },
  glowTop: { top: -210, right: -170, backgroundColor: colors.navySoft, opacity: 0.55 },
  glowBottom: { bottom: -230, left: -190, backgroundColor: colors.cyan, opacity: 0.1 },
  stage: { alignItems: 'center' },
  tileSlot: { width: TILE, height: TILE, alignItems: 'center', justifyContent: 'center' },
  tile: {
    width: TILE,
    height: TILE,
    borderRadius: TILE * 0.3,
    backgroundColor: colors.white,
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
  },
  // Same inset as the native splash image (scripts/make-logo.py: 14% each side).
  mark: { width: TILE * 0.72, height: TILE * 0.72 },
  shine: {
    position: 'absolute',
    top: -TILE * 0.3,
    width: TILE * 0.28,
    height: TILE * 1.6,
    backgroundColor: 'rgba(47,164,215,0.18)',
  },
  ring: {
    position: 'absolute',
    width: TILE,
    height: TILE,
    borderRadius: TILE * 0.3,
    borderWidth: 1.5,
    borderColor: colors.cyan,
  },
  wordmark: { flexDirection: 'row', height: 40, marginTop: 24, alignItems: 'center' },
  letter: { fontFamily: font.extrabold, fontSize: 32, lineHeight: 40, color: colors.white, letterSpacing: -0.4 },
  tagline: {
    height: 16,
    marginTop: 6,
    fontFamily: font.semibold,
    fontSize: 11,
    lineHeight: 16,
    color: colors.cyan,
  },
  track: {
    width: 120,
    height: 3,
    marginTop: 26,
    borderRadius: 2,
    backgroundColor: 'rgba(255,255,255,0.12)',
    overflow: 'hidden',
  },
  bar: { flex: 1, borderRadius: 2, backgroundColor: colors.cyan, transformOrigin: 'left' },
});
