import { useState } from 'react';

import { digits } from '@/lib/format';

import { Field } from './Field';

/** "YYYY-MM-DD" ⇄ "DD/MM/YYYY" as the customer types. */
function toDisplay(iso: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? '');
  return m ? `${m[3]}/${m[2]}/${m[1]}` : '';
}

function mask(raw: string): string {
  const d = digits(raw).slice(0, 8);
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

type Props = {
  label: string;
  value: string | null | undefined;
  onChange: (iso: string | null) => void;
  error?: string | null;
  optional?: boolean;
};

/** Typed date entry (DD/MM/YYYY): faster than a spinner for birth dates, works everywhere. */
export function DateField({ label, value, onChange, error, optional }: Props) {
  const [text, setText] = useState(toDisplay(value));
  // Adopt a new value from outside (e.g. draft loaded) without an effect.
  const [seen, setSeen] = useState(value);
  if (value !== seen) {
    setSeen(value);
    if (value && value !== isoFromDisplay(text)) setText(toDisplay(value));
  }

  const complete = text.length === 10;
  const invalid = complete && !isoFromDisplay(text);
  return (
    <Field
      label={label}
      optional={optional}
      value={text}
      placeholder="DD/MM/YYYY"
      keyboardType="number-pad"
      maxLength={10}
      onChangeText={(t) => {
        const next = mask(t);
        setText(next);
        onChange(next.length === 10 ? isoFromDisplay(next) : null);
      }}
      error={invalid ? 'Enter a real date as DD/MM/YYYY.' : error}
    />
  );
}
