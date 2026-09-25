import Ionicons from '@expo/vector-icons/Ionicons';
import { useMemo, useState } from 'react';
import { FlatList, Modal, Platform, Pressable, StyleSheet, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { colors, font, HIT, radius, space } from '@/theme/tokens';

import { Text } from './Text';

export type Option = { value: string; label: string };

type Props = {
  label: string;
  value: string | null | undefined;
  options: Option[];
  onChange: (value: string, option: Option) => void;
  placeholder?: string;
  error?: string | null;
  optional?: boolean;
  loading?: boolean;
  /** Show a search box (long lists like banks). */
  searchable?: boolean;
};

/** A field that opens a full-height picker; search for long lists. */
export function SelectField({ label, value, options, onChange, placeholder = 'Select', error, optional, loading, searchable }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const selected = options.find((o) => o.value === value);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? options.filter((o) => o.label.toLowerCase().includes(q)) : options;
  }, [options, query]);

  return (
    <View style={{ gap: 6 }}>
      <Text variant="small" style={{ fontFamily: font.semibold }}>
        {label}
        {optional ? <Text variant="small" muted>{'  (optional)'}</Text> : null}
      </Text>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`${label}: ${selected?.label ?? 'not selected'}`}
        accessibilityHint="Opens a list to choose from"
        disabled={loading}
        onPress={() => setOpen(true)}
        style={[styles.box, error ? { borderColor: colors.error } : null]}>
        <Text
          variant="body"
          style={{ flex: 1, fontFamily: font.semibold }}
          color={selected ? colors.text : colors.textFaint}
          numberOfLines={1}>
          {loading ? 'Loading…' : (selected?.label ?? placeholder)}
        </Text>
        <Ionicons name="chevron-down" size={18} color={colors.textMuted} />
      </Pressable>
      {error ? (
        <Text variant="small" color={colors.error}>
          {error}
        </Text>
      ) : null}

      <Modal visible={open} animationType="slide" presentationStyle="pageSheet" onRequestClose={() => setOpen(false)}>
        <SafeAreaView style={styles.sheet} edges={['top', 'bottom']}>
          <View style={styles.sheetHeader}>
            <Text variant="heading">{label}</Text>
            <Pressable accessibilityRole="button" accessibilityLabel="Close" onPress={() => setOpen(false)} style={styles.close}>
              <Ionicons name="close" size={24} color={colors.navy} />
            </Pressable>
          </View>
          {searchable ? (
            <View style={styles.search}>
              <Ionicons name="search" size={18} color={colors.textMuted} />
              <TextInput
                value={query}
                onChangeText={setQuery}
                placeholder="Search"
                placeholderTextColor={colors.textFaint}
                autoFocus
                autoCorrect={false}
                style={styles.searchInput}
                accessibilityLabel={`Search ${label}`}
              />
            </View>
          ) : null}
          <FlatList
            data={filtered}
            keyExtractor={(o) => o.value}
            keyboardShouldPersistTaps="handled"
            initialNumToRender={20}
            ListEmptyComponent={
              <Text muted align="center" style={{ padding: space.xl }}>
                No matches
              </Text>
            }
            renderItem={({ item }) => {
              const on = item.value === value;
              return (
                <Pressable
                  accessibilityRole="radio"
                  accessibilityState={{ checked: on }}
                  onPress={() => {
                    onChange(item.value, item);
                    setOpen(false);
                    setQuery('');
                  }}
                  style={({ pressed }) => [styles.option, pressed && { backgroundColor: colors.surface }]}>
                  <Text variant="body" style={{ flex: 1, fontFamily: on ? font.bold : font.medium }}>
                    {item.label}
                  </Text>
                  {on ? <Ionicons name="checkmark" size={20} color={colors.cyanDeep} /> : null}
                </Pressable>
              );
            }}
          />
        </SafeAreaView>
      </Modal>
    </View>
  );
}

export const toOptions = (values: string[]): Option[] => values.map((v) => ({ value: v, label: v }));

const styles = StyleSheet.create({
  box: {
    flexDirection: 'row',
    alignItems: 'center',
    minHeight: HIT + 4,
    borderWidth: 1.5,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: colors.card,
    paddingHorizontal: space.md,
    gap: space.xs,
  },
  sheet: { flex: 1, backgroundColor: colors.card },
  sheetHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingLeft: space.lg,
    paddingRight: space.xs,
    paddingVertical: space.xs,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  close: { width: HIT, height: HIT, alignItems: 'center', justifyContent: 'center' },
  search: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.xs,
    margin: space.md,
    paddingHorizontal: space.md,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    minHeight: HIT,
  },
  searchInput: {
    flex: 1,
    minWidth: 0,
    fontFamily: font.medium,
    fontSize: 16,
    color: colors.text,
    paddingVertical: space.sm,
    ...(Platform.OS === 'web' ? ({ outlineStyle: 'none' } as object) : null),
  },
  option: {
    flexDirection: 'row',
    alignItems: 'center',
    minHeight: HIT + 4,
    paddingHorizontal: space.lg,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
});
