import Ionicons from '@expo/vector-icons/Ionicons';
import { Modal, Platform, Pressable, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { colors, HIT, radius, space } from '@/theme/tokens';

import { Text } from './Text';

export type SheetAction = { label: string; icon: keyof typeof Ionicons.glyphMap; onPress: () => void };

/** Bottom sheet of actions (Android's Alert caps at 3 buttons). */
export function ActionSheet({
  visible,
  title,
  actions,
  onClose,
}: {
  visible: boolean;
  title: string;
  actions: SheetAction[];
  onClose: () => void;
}) {
  const insets = useSafeAreaInsets();
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose} statusBarTranslucent>
      <Pressable style={styles.backdrop} onPress={onClose} accessibilityLabel="Close" accessibilityRole="button" />
      <View style={[styles.sheet, { paddingBottom: insets.bottom + space.sm }]}>
        <View style={styles.grabber} />
        <Text variant="heading" style={styles.title}>
          {title}
        </Text>
        {actions.map((a) => (
          <Pressable
            key={a.label}
            accessibilityRole="button"
            onPress={() => {
              onClose();
              // Native: let the modal close before a system picker opens over it.
              // Web: pickers only open synchronously inside the user's tap.
              if (Platform.OS === 'web') a.onPress();
              else setTimeout(a.onPress, 250);
            }}
            style={({ pressed }) => [styles.item, pressed && { backgroundColor: colors.surface }]}>
            <View style={styles.icon}>
              <Ionicons name={a.icon} size={20} color={colors.navy} />
            </View>
            <Text variant="bodyStrong">{a.label}</Text>
          </Pressable>
        ))}
        <Pressable accessibilityRole="button" onPress={onClose} style={styles.cancel}>
          <Text variant="bodyStrong" color={colors.textMuted}>
            Cancel
          </Text>
        </Pressable>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: colors.overlay },
  sheet: {
    backgroundColor: colors.card,
    borderTopLeftRadius: radius.xl,
    borderTopRightRadius: radius.xl,
    paddingHorizontal: space.md,
    paddingTop: space.sm,
  },
  grabber: { alignSelf: 'center', width: 40, height: 5, borderRadius: 3, backgroundColor: colors.border, marginBottom: space.sm },
  title: { paddingHorizontal: space.xs, marginBottom: space.xs },
  item: { flexDirection: 'row', alignItems: 'center', gap: space.md, minHeight: HIT + 8, paddingHorizontal: space.xs, borderRadius: radius.md },
  icon: { width: 40, height: 40, borderRadius: 20, backgroundColor: colors.surfaceNav, alignItems: 'center', justifyContent: 'center' },
  cancel: { minHeight: HIT, alignItems: 'center', justifyContent: 'center', marginTop: space.xs },
});
