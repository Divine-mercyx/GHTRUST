import { useRef, useState, type ComponentRef, type PropsWithChildren, type ReactNode } from 'react';
import { RefreshControl, StyleSheet, View } from 'react-native';
import { KeyboardAwareScrollView, KeyboardStickyView } from 'react-native-keyboard-controller';
import { SafeAreaView, useSafeAreaInsets, type Edge } from 'react-native-safe-area-context';

import { colors, space } from '@/theme/tokens';

type Props = PropsWithChildren<{
  /** Pull to refresh. */
  onRefresh?: () => void;
  refreshing?: boolean;
  /** Pinned under the scroll area (primary action). Rides above the keyboard. */
  footer?: ReactNode;
  /** Screens with a native header only need the bottom edge. */
  edges?: Edge[];
  scroll?: boolean;
  background?: string;
  /** Chat-style: keep the newest content (the end) in view as it grows. */
  stickToEnd?: boolean;
}>;

// Space kept between the focused field and whatever sits above the keyboard.
const FIELD_GAP = 16;

/**
 * Page wrapper. With the keyboard open, the focused field scrolls into view above it and
 * the footer moves up with it (react-native-keyboard-controller). Android draws edge to
 * edge, so the window no longer shrinks for the keyboard; this handles both platforms.
 */
export function Screen({
  children,
  onRefresh,
  refreshing = false,
  footer,
  edges = ['top', 'bottom'],
  scroll = true,
  background = colors.surface,
  stickToEnd = false,
}: Props) {
  const insets = useSafeAreaInsets();
  const scroller = useRef<ComponentRef<typeof KeyboardAwareScrollView>>(null);
  const [footerHeight, setFooterHeight] = useState(0);
  // The footer sits above the bottom safe area; with the keyboard up that area is
  // covered, so drop the footer by it to rest right on the keyboard.
  const bottomInset = edges.includes('bottom') ? insets.bottom : 0;

  const body = scroll ? (
    <KeyboardAwareScrollView
      ref={scroller}
      onContentSizeChange={stickToEnd ? () => scroller.current?.scrollToEnd({ animated: true }) : undefined}
      bottomOffset={(footer ? footerHeight : 0) + FIELD_GAP}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
      keyboardDismissMode="interactive"
      showsVerticalScrollIndicator={false}
      refreshControl={
        onRefresh ? (
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.navy} colors={[colors.navy]} />
        ) : undefined
      }>
      {children}
    </KeyboardAwareScrollView>
  ) : (
    <View style={[styles.content, styles.fill]}>{children}</View>
  );

  return (
    <SafeAreaView edges={edges} style={[styles.fill, { backgroundColor: background }]}>
      {body}
      {footer ? (
        <KeyboardStickyView offset={{ closed: 0, opened: bottomInset }}>
          <View
            style={[styles.footer, { backgroundColor: background }]}
            onLayout={(e) => setFooterHeight(e.nativeEvent.layout.height)}>
            {footer}
          </View>
        </KeyboardStickyView>
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  content: { padding: space.lg, paddingBottom: space.xxl, gap: space.md, width: '100%', maxWidth: 640, alignSelf: 'center' },
  footer: {
    paddingHorizontal: space.lg,
    paddingTop: space.sm,
    paddingBottom: space.sm,
    gap: space.sm,
    width: '100%',
    maxWidth: 640,
    alignSelf: 'center',
  },
});
