import Ionicons from '@expo/vector-icons/Ionicons';
import { Pressable, StyleSheet, View } from 'react-native';

import type { Application, LoanProduct } from '@/api/types';
import { Card } from '@/components/Card';
import { Text } from '@/components/Text';
import { naira } from '@/lib/format';
import { CADENCE } from '@/lib/status';
import { colors, font, HIT, space } from '@/theme/tokens';

import { PAGES, submitProblems, type PageId } from './config';
import type { Draft } from './draft';

type Props = {
  application: Application;
  product: LoanProduct;
  draft: Draft;
  pages: PageId[];
  agreed: boolean;
  onAgree: (v: boolean) => void;
  onEdit: (page: PageId) => void;
  submitErrors: string[];
};

export function ReviewPage({ application, product, draft, pages, agreed, onAgree, onEdit, submitErrors }: Props) {
  const f = draft.form;
  const months = Number(draft.product.tenure_months || 0);
  const amount = Number(f.requested_amount || 0);
  const docsDone = application.document_checklist.filter((d) => d.uploaded && d.status !== 'rejected').length;
  const cadence = product.repayment_cadence_options.map((c) => CADENCE[c] ?? c).join(' / ');

  const section = (page: PageId, rows: [string, string | undefined | null][]) =>
    pages.includes(page) ? (
      <Card key={page} style={{ gap: space.xs }}>
        <View style={styles.head}>
          <Text variant="heading">{PAGES[page].title}</Text>
          <Pressable accessibilityRole="button" accessibilityLabel={`Edit ${PAGES[page].title}`} onPress={() => onEdit(page)} style={styles.edit}>
            <Text variant="small" color={colors.cyanDeep} style={{ fontFamily: font.bold }}>
              Edit
            </Text>
          </Pressable>
        </View>
        {rows.map(([label, value]) => (
          <View key={label} style={styles.line}>
            <Text variant="small" muted style={{ flex: 1 }}>
              {label}
            </Text>
            <Text variant="small" style={{ flex: 1.4, textAlign: 'right', fontFamily: font.semibold }} color={value ? colors.text : colors.error}>
              {value || 'Missing'}
            </Text>
          </View>
        ))}
      </Card>
    ) : null;

  return (
    <View style={{ gap: space.md }}>
      {submitErrors.length ? (
        <Card style={styles.errors}>
          <Text variant="heading" color={colors.error}>
            A few things to fix
          </Text>
          {submitProblems(submitErrors).map(({ text, page }) => {
            return (
              <Pressable
                key={text}
                disabled={!page || !pages.includes(page)}
                onPress={() => page && onEdit(page)}
                accessibilityRole="button"
                style={styles.errorRow}>
                <Ionicons name="alert-circle" size={16} color={colors.error} />
                <Text variant="small" style={{ flex: 1 }}>
                  {text}
                </Text>
                {page && pages.includes(page) ? <Ionicons name="chevron-forward" size={16} color={colors.textMuted} /> : null}
              </Pressable>
            );
          })}
        </Card>
      ) : null}

      <Card style={styles.summary}>
        <Text variant="caption" color={colors.cyan}>
          {product.name.toUpperCase()}
        </Text>
        <Text variant="display" color={colors.white}>
          {amount ? naira(amount) : '—'}
        </Text>
        <Text variant="small" color="rgba(255,255,255,0.8)">
          {months ? `Over ${months} month${months === 1 ? '' : 's'}` : 'Tenure not set'} · {cadence} repayments
        </Text>
        <Text variant="small" color="rgba(255,255,255,0.65)" style={{ marginTop: space.xs }}>
          {Number(product.interest_rate_pct_monthly)}% monthly interest · {Number(product.processing_fee_pct)}% processing fee. Final
          terms are confirmed when your loan is approved.
        </Text>
      </Card>

      {section('request', [
        ['Purpose', f.purpose],
        ['Monthly income', f.monthly_income ? naira(f.monthly_income) : null],
        ['Repayment source', f.source_of_repayment],
      ])}
      {section('about', [
        ['Name', f.full_name],
        ['Phone', f.phone],
        ['Address', f.residential_address],
      ])}
      {section('bank', [
        ['Bank', f.bank_name],
        ['Account', f.bank_account_number ? `•••• ${f.bank_account_number.slice(-4)}` : null],
        ['Account name', f.bank_account_name],
      ])}
      {section('kin', [
        ['Name', f.next_of_kin_name],
        ['Phone', f.next_of_kin_phone],
        ['Relationship', f.next_of_kin_relationship],
      ])}
      {section('guarantor', [
        ['Guarantors', draft.guarantors.filter((g) => g.full_name?.trim()).map((g) => g.full_name).join(', ')],
        ['Collateral', draft.collaterals.length ? `${draft.collaterals.length} item(s)` : 'None'],
      ])}
      {section('documents', [['Uploaded', `${docsDone} of ${application.document_checklist.length}`]])}

      <Pressable
        accessibilityRole="checkbox"
        accessibilityState={{ checked: agreed }}
        accessibilityLabel="I confirm the information is true and authorise GH Trust to verify it"
        onPress={() => onAgree(!agreed)}
        style={styles.agree}>
        <View style={[styles.box, agreed && styles.boxOn]}>{agreed ? <Ionicons name="checkmark" size={16} color={colors.white} /> : null}</View>
        <Text variant="small" style={{ flex: 1 }}>
          I confirm the information I've given is true and complete, and I authorise GH Trust to verify it, including with
          credit bureaus.
        </Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  head: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  edit: { minHeight: HIT - 8, minWidth: HIT, alignItems: 'flex-end', justifyContent: 'center' },
  line: { flexDirection: 'row', gap: space.md, paddingVertical: 2 },
  summary: { backgroundColor: colors.navy, gap: 4 },
  errors: { gap: space.xs, borderWidth: 1.5, borderColor: colors.error },
  errorRow: { flexDirection: 'row', alignItems: 'center', gap: space.xs, minHeight: 36 },
  agree: { flexDirection: 'row', gap: space.sm, alignItems: 'flex-start', paddingVertical: space.sm, minHeight: HIT },
  box: {
    width: 24,
    height: 24,
    borderRadius: 6,
    borderWidth: 2,
    borderColor: colors.borderStrong,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 2,
  },
  boxOn: { backgroundColor: colors.navy, borderColor: colors.navy },
});
