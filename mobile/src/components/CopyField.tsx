import Ionicons from '@expo/vector-icons/Ionicons';
import * as Clipboard from 'expo-clipboard';
import * as Haptics from 'expo-haptics';
import { useState } from 'react';
import { Platform, Pressable, StyleSheet, View } from 'react-native';

import { colors, HIT, space } from '@/theme/tokens';

import { Text } from './Text';

/** A label/value line with a copy button (account numbers, references). */
export function CopyField({ label, value, last }: { label: string; value: string; last?: boolean }) {
  const [copied, setCopied] = useState(false);
  return (
    <View style={[styles.row, !last && styles.divider]}>
      <View style={{ flex: 1 }}>
        <Text variant="small" muted>
          {label}
        </Text>
        <Text variant="heading" selectable>
          {value}
        </Text>
      </View>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={copied ? `${label} copied` : `Copy ${label}`}
        hitSlop={8}
        onPress={async () => {
          await Clipboard.setStringAsync(value);
          if (Platform.OS !== 'web') Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => undefined);
          setCopied(true);
          setTimeout(() => setCopied(false), 1800);
        }}
        style={styles.copy}>
        <Ionicons name={copied ? 'checkmark' : 'copy-outline'} size={18} color={copied ? colors.success : colors.cyanDeep} />
        <Text variant="small" color={copied ? colors.success : colors.cyanDeep}>
          {copied ? 'Copied' : 'Copy'}
        </Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: space.sm, paddingVertical: space.sm, minHeight: HIT + 8 },
  divider: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  copy: { flexDirection: 'row', alignItems: 'center', gap: 4, minHeight: HIT, paddingHorizontal: space.xs },
});
