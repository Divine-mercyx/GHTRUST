import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import type { ApplicationSummary, Loan } from '@/api/types';
import { date, naira, relativeDue } from '@/lib/format';
import { APPLICATION_TRACK, applicationStatus, loanStatus, trackIndex } from '@/lib/status';
import { colors, font, space } from '@/theme/tokens';

import { Badge } from './Badge';
import { Card } from './Card';
import { ProgressBar } from './States';
import { Text } from './Text';

const PRODUCT_NAME: Record<string, string> = {
  business_loan: 'Business loan',
  payday_loan: 'Payday loan',
  study_loan: 'Study loan',
  asset_loan: 'Asset loan',
  lpo_invoice_financing: 'Invoice financing',
};

export const productName = (code: string) => PRODUCT_NAME[code] ?? code;

export function LoanCard({ loan }: { loan: Loan }) {
  const s = loanStatus(loan.status);
  const paid = Number(loan.amount_paid);
  const total = Number(loan.total_repayable) || 1;
  const open = loan.status === 'active' || loan.status === 'overdue';
  return (
    <Card onPress={() => router.push(`/loans/${loan.id}`)} accessibilityLabel={`${productName(loan.product_type)}, ${s.label}`}>
      <View style={styles.between}>
        <Text variant="heading">{productName(loan.product_type)}</Text>
        <Badge label={s.label} tone={s.tone} />
      </View>
      <View style={[styles.between, { marginTop: space.md }]}>
        <View>
          <Text variant="caption" muted>
            OUTSTANDING
          </Text>
          <Text variant="title">{naira(loan.outstanding)}</Text>
        </View>
        {open && loan.next_due_date ? (
          <View style={{ alignItems: 'flex-end' }}>
            <Text variant="caption" muted>
              NEXT PAYMENT
            </Text>
            <Text variant="bodyStrong">{naira(loan.monthly_payment)}</Text>
            <Text variant="small" color={loan.status === 'overdue' ? colors.error : colors.textMuted}>
              {relativeDue(loan.next_due_date)}
            </Text>
          </View>
        ) : null}
      </View>
      <View style={{ marginTop: space.md, gap: 6 }}>
        <ProgressBar value={paid / total} color={loan.status === 'overdue' ? colors.error : colors.success} />
        <Text variant="small" muted>
          {naira(loan.amount_paid)} of {naira(loan.total_repayable)} repaid
        </Text>
      </View>
    </Card>
  );
}

export function ApplicationCard({ app }: { app: ApplicationSummary }) {
  const s = applicationStatus(app.status);
  const draft = app.status === 'draft';
  const amount = app.approved_amount ?? app.requested_amount;
  return (
    <Card
      onPress={() => router.push(draft ? `/apply/${app.id}` : `/applications/${app.id}`)}
      accessibilityLabel={`${app.product_name}, ${s.label}`}>
      <View style={styles.between}>
        <View style={{ flex: 1, gap: 2 }}>
          <Text variant="heading" numberOfLines={1}>
            {app.product_name}
          </Text>
          <Text variant="small" muted>
            {amount ? naira(amount) : 'Amount not set'} · {draft ? `Started ${date(app.created_at)}` : `Sent ${date(app.submitted_at)}`}
          </Text>
        </View>
        <Badge label={s.label} tone={s.tone} />
      </View>
      {draft ? (
        <View style={styles.cta}>
          <Text variant="small" color={colors.cyanDeep} style={{ fontFamily: font.semibold }}>
            Continue application
          </Text>
          <Ionicons name="arrow-forward" size={16} color={colors.cyanDeep} />
        </View>
      ) : trackIndex(app.status) >= 0 ? (
        <StatusTrack status={app.status} compact />
      ) : null}
    </Card>
  );
}

/** Submitted → In review → Approved → Paid out. */
export function StatusTrack({ status, compact }: { status: string; compact?: boolean }) {
  const at = trackIndex(status);
  const warn = status === 'documents_incomplete';
  return (
    <View style={[styles.track, compact && { marginTop: space.md }]} accessibilityLabel={`Progress: ${APPLICATION_TRACK[at] ?? ''}`}>
      {APPLICATION_TRACK.map((label, i) => {
        const done = i < at || (i === at && status === 'disbursed');
        const current = i === at && !done;
        const color = done ? colors.success : current ? (warn ? colors.warning : colors.cyan) : colors.border;
        return (
          <View key={label} style={styles.trackStep}>
            <View style={styles.trackLineRow}>
              <View style={[styles.trackLine, { backgroundColor: i === 0 ? 'transparent' : i <= at ? colors.success : colors.border }]} />
              <View style={[styles.trackDot, { borderColor: color, backgroundColor: done ? color : colors.card }]}>
                {done ? <Ionicons name="checkmark" size={11} color={colors.white} /> : current ? <View style={[styles.trackInner, { backgroundColor: color }]} /> : null}
              </View>
              <View
                style={[
                  styles.trackLine,
                  { backgroundColor: i === APPLICATION_TRACK.length - 1 ? 'transparent' : i < at ? colors.success : colors.border },
                ]}
              />
            </View>
            <Text
              variant="small"
              align="center"
              color={current || done ? colors.text : colors.textFaint}
              style={{ fontSize: 11, fontFamily: current ? font.bold : font.medium }}>
              {label}
            </Text>
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  between: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', gap: space.sm },
  cta: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginTop: space.md,
    paddingTop: space.sm,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
  },
  track: { flexDirection: 'row' },
  trackStep: { flex: 1, gap: 6 },
  trackLineRow: { flexDirection: 'row', alignItems: 'center' },
  trackLine: { flex: 1, height: 2 },
  trackDot: {
    width: 20,
    height: 20,
    borderRadius: 10,
    borderWidth: 2,
    alignItems: 'center',
    justifyContent: 'center',
  },
  trackInner: { width: 8, height: 8, borderRadius: 4 },
});
