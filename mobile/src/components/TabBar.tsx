import Ionicons from '@expo/vector-icons/Ionicons';
import { type Tabs } from 'expo-router';
import * as Haptics from 'expo-haptics';
import type { ComponentProps } from 'react';
import { Platform, Pressable, StyleSheet, View } from 'react-native';
import Animated, { FadeIn, LinearTransition } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { colors, font, radius, space } from '@/theme/tokens';

import { Text } from './Text';

export type TabBarProps = Parameters<NonNullable<ComponentProps<typeof Tabs>['tabBar']>>[0];
type IconName = keyof typeof Ionicons.glyphMap;

/** Icon per tab route: [outline, filled]. */
export const TAB_ICONS: Record<string, [IconName, IconName]> = {
  index: ['home-outline', 'home'],
  loans: ['document-text-outline', 'document-text'],
  invest: ['trending-up-outline', 'trending-up'],
  wallet: ['wallet-outline', 'wallet'],
  profile: ['person-circle-outline', 'person-circle'],
};

/**
 * Floating white tab bar with rounded ends. The active tab grows into a gold pill with its
 * label; the others show their icon only (their name is still read out by screen readers).
 * It is laid out (not absolutely positioned), so screens never scroll under it.
 */
export function TabBar({ state, descriptors, navigation, hidden }: TabBarProps & { hidden: Set<string> }) {
  const { bottom } = useSafeAreaInsets();
  return (
    <View style={[styles.wrap, { paddingBottom: Math.max(bottom, space.sm) }]}>
      <View style={styles.bar} accessibilityRole="tablist">
        {state.routes.map((route, index) => {
          if (hidden.has(route.name)) return null;
          const { options } = descriptors[route.key];
          const label = typeof options.title === 'string' ? options.title : route.name;
          const focused = state.index === index;
          const [outline, filled] = TAB_ICONS[route.name] ?? ['ellipse-outline', 'ellipse'];
          const onPress = () => {
            const event = navigation.emit({ type: 'tabPress', target: route.key, canPreventDefault: true });
            if (!focused && !event.defaultPrevented) {
              if (Platform.OS !== 'web') Haptics.selectionAsync().catch(() => undefined);
              navigation.navigate(route.name, route.params);
            }
          };
          return (
            <Pressable
              key={route.key}
              accessibilityRole="tab"
              accessibilityState={{ selected: focused }}
              accessibilityLabel={label}
              onPress={onPress}
              onLongPress={() => navigation.emit({ type: 'tabLongPress', target: route.key })}
              style={[styles.item, focused && styles.itemOn]}>
              <Animated.View layout={LinearTransition.springify().damping(18)} style={[styles.pill, focused && styles.pillOn]}>
                <Ionicons name={focused ? filled : outline} size={21} color={focused ? colors.navy : INACTIVE} />
                {focused ? (
                  <Animated.View entering={FadeIn.duration(180)}>
                    <Text variant="small" color={colors.navy} style={styles.label} numberOfLines={1}>
                      {label}
                    </Text>
                  </Animated.View>
                ) : null}
              </Animated.View>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const INACTIVE = colors.textFaint;

const styles = StyleSheet.create({
  wrap: { backgroundColor: colors.surface, paddingHorizontal: space.md, paddingTop: space.xs },
  bar: {
    flexDirection: 'row',
    backgroundColor: colors.card,
    borderRadius: radius.xl,
    paddingVertical: space.xs,
    paddingHorizontal: space.xs,
    maxWidth: 640,
    width: '100%',
    alignSelf: 'center',
    ...Platform.select({
      ios: { shadowColor: colors.navy, shadowOpacity: 0.12, shadowRadius: 20, shadowOffset: { width: 0, height: 8 } },
      android: { elevation: 10 },
      default: { boxShadow: '0 8px 24px rgba(27,47,107,.12)' },
    }),
  },
  item: { flex: 1, alignItems: 'center', minHeight: 52, justifyContent: 'center' },
  // The active tab takes more room for its label.
  itemOn: { flex: 1.9 },
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    height: 42,
    minWidth: 46,
    paddingHorizontal: space.sm,
    borderRadius: radius.pill,
  },
  pillOn: { backgroundColor: colors.highlight, paddingHorizontal: space.md },
  label: { fontFamily: font.bold, fontSize: 13, lineHeight: 16 },
});
