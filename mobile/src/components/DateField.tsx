import DateTimePicker, { type DateTimePickerEvent } from '@react-native-community/datetimepicker';
import { useState } from 'react';
import { Modal, Platform, Pressable, StyleSheet, View } from 'react-native';

import { date } from '@/lib/format';
import { colors, font, HIT, radius, space } from '@/theme/tokens';

import { Field } from './Field';
import { Text } from './Text';

/** "YYYY-MM-DD" ⇄ "DD/MM/YYYY" as the customer types (web fallback). */
function toDisplay(iso: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? '');
  return m ? `${m[3]}/${m[2]}/${m[1]}` : '';
}

function mask(raw: string): string {
  const d = raw.replace(/\D/g, '').slice(0, 8);
  return [d.slice(0, 2), d.slice(2, 4), d.slice(4)].filter(Boolean).join('/');
}

export function isoFromDisplay(display: string): string | null {
  const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(display);
  if (!m) return null;
  const [, dd, mm, yyyy] = m;
  const d = new Date(Number(yyyy), Number(mm) - 1, Number(dd));
  const valid = d.getFullYear() === Number(yyyy) && d.getMonth() === Number(mm) - 1 && d.getDate() === Number(dd);
  return valid ? `${yyyy}-${mm}-${dd}` : null;
}

function isoToDate(iso: string | null | undefined): Date {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? '');
  if (m) return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), 12, 0, 0);
  const d = new Date();
  d.setFullYear(d.getFullYear() - 25);
  return d;
}

function toIso(d: Date): string {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

const MAX_DATE = new Date();
const MIN_DATE = new Date(MAX_DATE.getFullYear() - 100, 0, 1);

type Props = {
  label: string;
  value: string | null | undefined;
  onChange: (iso: string | null) => void;
  error?: string | null;
  optional?: boolean;
  maximumDate?: Date;
  minimumDate?: Date;
};

/** Native calendar on iOS/Android; typed DD/MM/YYYY on web. */
export function DateField({
  label,
  value,
  onChange,
  error,
  optional,
  maximumDate = MAX_DATE,
  minimumDate = MIN_DATE,
}: Props) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(() => isoToDate(value));
  const [webText, setWebText] = useState(toDisplay(value));
  const [seen, setSeen] = useState(value);
  if (value !== seen) {
    setSeen(value);
    setDraft(isoToDate(value));
    if (value && value !== isoFromDisplay(webText)) setWebText(toDisplay(value));
  }

  if (Platform.OS === 'web') {
    const complete = webText.length === 10;
    const invalid = complete && !isoFromDisplay(webText);
    return (
      <Field
        label={label}
        optional={optional}
        value={webText}
        placeholder="DD/MM/YYYY"
        keyboardType="number-pad"
        maxLength={10}
        onChangeText={(t) => {
          const next = mask(t);
          setWebText(next);
          onChange(next.length === 10 ? isoFromDisplay(next) : null);
        }}
        error={invalid ? 'Enter a real date as DD/MM/YYYY.' : error}
      />
    );
  }

  const display = value ? date(value) : 'Select date';
  const showError = error;

  const commit = (d: Date) => {
    onChange(toIso(d));
    setOpen(false);
  };

  const onPickerChange = (event: DateTimePickerEvent, selected?: Date) => {
    if (event.type === 'dismissed') {
      setOpen(false);
      return;
    }
    if (selected) {
      setDraft(selected);
      if (Platform.OS === 'android') commit(selected);
    }
  };

  return (
    <View style={styles.wrap}>
      <Text variant="small" style={styles.label}>
        {label}
        {optional ? <Text variant="small" muted>{'  (optional)'}</Text> : null}
      </Text>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`${label}, ${display}`}
        accessibilityHint="Opens the date picker"
        onPress={() => setOpen(true)}
        style={[styles.box, showError ? styles.boxError : null]}>
        <Text variant="body" color={value ? colors.text : colors.textFaint}>
          {value ? display : 'Tap to choose date'}
        </Text>
      </Pressable>
      {showError ? (
        <Text variant="small" color={colors.error} style={styles.error}>
          {showError}
        </Text>
      ) : null}

      {Platform.OS === 'android' && open ? (
        <DateTimePicker
          value={draft}
          mode="date"
          display="default"
          maximumDate={maximumDate}
          minimumDate={minimumDate}
          onChange={onPickerChange}
        />
      ) : null}

      {Platform.OS === 'ios' ? (
        <Modal visible={open} transparent animationType="slide" onRequestClose={() => setOpen(false)}>
          <Pressable style={styles.backdrop} onPress={() => setOpen(false)} />
          <View style={styles.sheet}>
            <View style={styles.sheetBar}>
              <Pressable accessibilityRole="button" onPress={() => setOpen(false)} hitSlop={12}>
                <Text variant="bodyStrong" color={colors.textMuted}>
                  Cancel
                </Text>
              </Pressable>
              <Text variant="bodyStrong">{label}</Text>
              <Pressable accessibilityRole="button" onPress={() => commit(draft)} hitSlop={12}>
                <Text variant="bodyStrong" color={colors.cyanDeep}>
                  Done
                </Text>
              </Pressable>
            </View>
            <DateTimePicker
              value={draft}
              mode="date"
              display="spinner"
              maximumDate={maximumDate}
              minimumDate={minimumDate}
              onChange={(_, selected) => selected && setDraft(selected)}
              themeVariant="light"
              style={{ height: 220 }}
            />
          </View>
        </Modal>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: space.xs },
  label: { fontFamily: font.semibold, color: colors.text },
  box: {
    minHeight: HIT,
    borderWidth: 1.5,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: space.md,
    justifyContent: 'center',
    backgroundColor: colors.card,
  },
  boxError: { borderColor: colors.error },
  error: { marginTop: 2 },
  backdrop: { flex: 1, backgroundColor: colors.overlay },
  sheet: {
    backgroundColor: colors.card,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    paddingBottom: space.xl,
  },
  sheetBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: space.lg,
    paddingVertical: space.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
});
