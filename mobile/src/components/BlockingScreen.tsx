import Ionicons from '@expo/vector-icons/Ionicons';
import * as Linking from 'expo-linking';
import { StyleSheet, View } from 'react-native';

import { colors, space } from '@/theme/tokens';

import { Button } from './Button';
import { Screen } from './Screen';
import { Text } from './Text';

// Store links, set once the app is published (EXPO_PUBLIC_*_STORE_URL).
const STORE_URL = {
  ios: process.env.EXPO_PUBLIC_IOS_STORE_URL,
  android: process.env.EXPO_PUBLIC_ANDROID_STORE_URL,
};

type Props =
  | { kind: 'update'; platform?: 'ios' | 'android' }
  | { kind: 'maintenance'; message?: string | null; onRetry: () => void };

/** Full-screen stop for a forced update or maintenance window. */
export function BlockingScreen(props: Props) {
  const update = props.kind === 'update';
  const storeUrl = update && props.platform ? STORE_URL[props.platform] : undefined;
  return (
    <Screen scroll={false}>
      <View style={styles.center}>
        <View style={styles.icon}>
          <Ionicons name={update ? 'arrow-up-circle' : 'construct'} size={36} color={colors.navy} />
        </View>
        <Text variant="title" align="center">
          {update ? 'Update required' : "We'll be right back"}
        </Text>
        <Text muted align="center">
          {update
            ? 'This version of GH Trust is no longer supported. Please update to continue.'
            : (props.message ?? 'GH Trust is undergoing scheduled maintenance. Please try again shortly.')}
        </Text>
      </View>
      {update ? (
        storeUrl ? (
          <Button title="Update now" icon="download-outline" onPress={() => Linking.openURL(storeUrl)} />
        ) : null
      ) : (
        <Button title="Try again" icon="refresh" variant="secondary" onPress={props.onRetry} />
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: space.sm, paddingHorizontal: space.md },
  icon: {
    width: 76,
    height: 76,
    borderRadius: 38,
    backgroundColor: colors.mint,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: space.sm,
  },
});
