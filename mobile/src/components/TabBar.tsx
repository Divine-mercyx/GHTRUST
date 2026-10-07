import Ionicons from '@expo/vector-icons/Ionicons';
import { type Tabs } from 'expo-router';
import * as Haptics from 'expo-haptics';
import type { ComponentProps } from 'react';
import { Platform, Pressable, StyleSheet, View } from 'react-native';
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
 * Floating navy tab bar with rounded ends. The active tab sits on a lighter pill.
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
              style={styles.item}>
              <View style={[styles.pill, focused && styles.pillOn]}>
                <Ionicons name={focused ? filled : outline} size={22} color={focused ? colors.white : INACTIVE} />
              </View>
              <Text variant="small" color={focused ? colors.white : INACTIVE} style={styles.label} numberOfLines={1}>
                {label}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const INACTIVE = 'rgba(255,255,255,0.6)';

const styles = StyleSheet.create({
  wrap: { backgroundColor: colors.surface, paddingHorizontal: space.md, paddingTop: space.xs },
  bar: {
    flexDirection: 'row',
    backgroundColor: colors.navy,
    borderRadius: radius.xl,
    paddingVertical: space.xs,
    paddingHorizontal: space.xs,
    maxWidth: 640,
    width: '100%',
    alignSelf: 'center',
    ...Platform.select({
      ios: { shadowColor: colors.navy, shadowOpacity: 0.25, shadowRadius: 16, shadowOffset: { width: 0, height: 8 } },
      android: { elevation: 10 },
      default: { boxShadow: '0 8px 24px rgba(27,47,107,.25)' },
    }),
  },
  item: { flex: 1, alignItems: 'center', gap: 2, minHeight: 52, justifyContent: 'center' },
  pill: { width: 48, height: 30, borderRadius: radius.pill, alignItems: 'center', justifyContent: 'center' },
  pillOn: { backgroundColor: colors.navySoft },
  label: { fontFamily: font.semibold, fontSize: 11, lineHeight: 14 },
});
