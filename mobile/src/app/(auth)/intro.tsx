import * as Haptics from 'expo-haptics';
import { StatusBar } from 'expo-status-bar';
import { useState, type ComponentType } from 'react';
import { Platform, Pressable, StyleSheet, useWindowDimensions, View } from 'react-native';
import Animated, {
  interpolate,
  interpolateColor,
  useAnimatedReaction,
  useAnimatedRef,
  useAnimatedScrollHandler,
  useAnimatedStyle,
  useSharedValue,
  type SharedValue,
} from 'react-native-reanimated';
import { SafeAreaView } from 'react-native-safe-area-context';
import { scheduleOnRN } from 'react-native-worklets';

import { Button } from '@/components/Button';
import { LoansArt, SecureArt, TrackArt } from '@/components/IntroArt';
import { Text } from '@/components/Text';
import { finishIntro } from '@/lib/intro';
import { colors, HIT, radius, space } from '@/theme/tokens';

const SLIDES: { title: string; body: string; Art: ComponentType<{ active: boolean }> }[] = [
  {
    title: 'Loans that fit your life',
    body: 'Business, payday, study, group and LPO financing. Apply from your phone in minutes, no queues.',
    Art: LoansArt,
  },
  {
    title: 'Know where you stand',
    body: 'Follow your application from review to payout, with an update at every step.',
    Art: TrackArt,
  },
  {
    title: 'Safe with you, always',
    body: "BVN-verified sign-up, and your phone's Face ID or fingerprint keeps your account locked.",
    Art: SecureArt,
  },
];

/** Shown once, on first launch: what GH Trust does, before the welcome screen. */
export default function Intro() {
  const { width } = useWindowDimensions();
  const scroller = useAnimatedRef<Animated.ScrollView>();
  const x = useSharedValue(0);
  const [page, setPage] = useState(0);
  const [controlsHeight, setControlsHeight] = useState(140);
  const [pagerHeight, setPagerHeight] = useState(0);
  const last = page === SLIDES.length - 1;

  const onScroll = useAnimatedScrollHandler((e) => {
    x.value = e.contentOffset.x;
  });
  useAnimatedReaction(
    () => Math.round(x.value / width),
    (now, before) => {
      if (now !== before) scheduleOnRN(setPage, now);
    },
  );

  const next = () => {
    if (Platform.OS !== 'web') Haptics.selectionAsync().catch(() => undefined);
    if (last) finishIntro();
    else scroller.current?.scrollTo({ x: (page + 1) * width, animated: true });
  };

  return (
    <View style={styles.fill}>
      <StatusBar style="light" />
      <SafeAreaView edges={['top']} style={styles.top}>
        <Pressable
          onPress={finishIntro}
          accessibilityRole="button"
          accessibilityLabel="Skip intro"
          hitSlop={12}
          style={[styles.skip, last && styles.hidden]}
          disabled={last}>
          <Text variant="bodyStrong" color="rgba(255,255,255,0.75)">
            Skip
          </Text>
        </Pressable>
      </SafeAreaView>

      <View style={[styles.sheet, { height: controlsHeight + COPY }]} />

      <View style={styles.pager} onLayout={(e) => setPagerHeight(e.nativeEvent.layout.height)}>
        <Animated.ScrollView
          ref={scroller}
          horizontal
          pagingEnabled
          bounces={false}
          showsHorizontalScrollIndicator={false}
          onScroll={onScroll}
          scrollEventThrottle={16}
          style={styles.pager}>
          {SLIDES.map((s, i) => (
            <Slide key={s.title} index={i} width={width} height={pagerHeight} x={x} active={page === i} {...s} />
          ))}
        </Animated.ScrollView>
      </View>

      <SafeAreaView
        edges={['bottom']}
        style={styles.controls}
        onLayout={(e) => setControlsHeight(e.nativeEvent.layout.height)}>
        <View style={styles.dots} accessibilityLabel={`Page ${page + 1} of ${SLIDES.length}`}>
          {SLIDES.map((s, i) => (
            <Dot key={s.title} index={i} width={width} x={x} />
          ))}
        </View>
        <Button
          title={last ? 'Get started' : 'Next'}
          icon={last ? undefined : 'arrow-forward'}
          onPress={next}
          style={styles.cta}
        />
      </SafeAreaView>
    </View>
  );
}

function Slide({
  index,
  width,
  height,
  x,
  active,
  title,
  body,
  Art,
}: (typeof SLIDES)[number] & {
  index: number;
  width: number;
  height: number;
  x: SharedValue<number>;
  active: boolean;
}) {
  const range = [(index - 1) * width, index * width, (index + 1) * width];
  const artStyle = useAnimatedStyle(() => ({
    opacity: interpolate(x.value, range, [0, 1, 0], 'clamp'),
    transform: [
      { translateX: interpolate(x.value, range, [width * 0.45, 0, -width * 0.45], 'clamp') },
      { scale: interpolate(x.value, range, [0.75, 1, 0.75], 'clamp') },
    ],
  }));
  const textStyle = useAnimatedStyle(() => ({
    opacity: interpolate(x.value, range, [0, 1, 0], 'clamp'),
    transform: [{ translateX: interpolate(x.value, range, [width * 0.2, 0, -width * 0.2], 'clamp') }],
  }));

  return (
    <View
      style={{ width, height: height || undefined }}
      accessible={active}
      importantForAccessibility={active ? 'yes' : 'no-hide-descendants'}>
      <View style={styles.stage}>
        <Animated.View style={artStyle}>
          <Art active={active} />
        </Animated.View>
      </View>
      <Animated.View style={[styles.copy, textStyle]}>
        <Text variant="display" align="center" style={styles.title}>
          {title}
        </Text>
        <Text muted align="center" style={styles.body}>
          {body}
        </Text>
      </Animated.View>
    </View>
  );
}

function Dot({ index, width, x }: { index: number; width: number; x: SharedValue<number> }) {
  const style = useAnimatedStyle(() => {
    const t = interpolate(x.value, [(index - 1) * width, index * width, (index + 1) * width], [0, 1, 0], 'clamp');
    return {
      width: 8 + t * 20,
      backgroundColor: interpolateColor(t, [0, 1], [colors.borderStrong, colors.cyan]),
    };
  });
  return <Animated.View style={[styles.dot, style]} />;
}

const COPY = 214; // height of each slide's words, which sit on the white panel with the buttons

const styles = StyleSheet.create({
  fill: { flex: 1, backgroundColor: colors.navy },
  top: { position: 'absolute', top: 0, left: 0, right: 0, zIndex: 2, alignItems: 'flex-end' },
  skip: { minHeight: HIT, justifyContent: 'center', paddingHorizontal: space.xl },
  hidden: { opacity: 0 },
  sheet: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: colors.card,
    borderTopLeftRadius: radius.xl + 8,
    borderTopRightRadius: radius.xl + 8,
  },
  pager: { flex: 1 },
  stage: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingTop: HIT },
  copy: {
    height: COPY,
    paddingHorizontal: space.xl,
    paddingTop: space.xl,
    gap: space.sm,
    maxWidth: 480,
    width: '100%',
    alignSelf: 'center',
  },
  title: { fontSize: 28, lineHeight: 34 },
  body: { paddingHorizontal: space.xs },
  controls: {
    backgroundColor: colors.card,
    paddingHorizontal: space.xl,
    paddingBottom: space.lg,
    gap: space.xl,
  },
  dots: { flexDirection: 'row', justifyContent: 'center', gap: 6 },
  dot: { height: 8, borderRadius: 4 },
  cta: { maxWidth: 480, width: '100%', alignSelf: 'center', backgroundColor: colors.navy },
});
