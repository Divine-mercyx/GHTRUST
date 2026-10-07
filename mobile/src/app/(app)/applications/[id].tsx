import { router, useLocalSearchParams } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import { Badge } from '@/components/Badge';
import { Button } from '@/components/Button';
import { Card, SectionHeader } from '@/components/Card';
import { StatusTrack } from '@/components/loans';
import { Screen } from '@/components/Screen';
import { Banner, CardSkeleton, ErrorState } from '@/components/States';
import { Text } from '@/components/Text';
import { DocumentChecklist } from '@/features/apply/DocumentChecklist';
import { dateTime, naira } from '@/lib/format';
import { useApplication, useLoans } from '@/lib/queries';
import { applicationStatus, CADENCE, trackIndex } from '@/lib/status';
import { colors, space } from '@/theme/tokens';

export default function ApplicationDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const app = useApplication(id);
  const loansQuery = useLoans();
  const a = app.data;

  if (app.isPending) {
    return (
      <Screen edges={['bottom']}>
        <CardSkeleton lines={3} />
        <CardSkeleton lines={4} />
      </Screen>
    );
  }
  if (app.isError || !a) {
    return (
      <Screen edges={['bottom']}>
        <ErrorState error={app.error} onRetry={() => app.refetch()} />
      </Screen>
    );
  }

  const s = applicationStatus(a.status);
  const loan = loansQuery.data?.items.find((l) => l.application_id === a.id);
  const needsDocs = a.status === 'documents_incomplete' || a.documents.some((d) => d.status === 'rejected');
  const offerWaiting =
    (a.status === 'offer_sent' || (a.status === 'approved' && !a.offer_accepted_at));
  const amount = a.approved_amount ?? a.requested_amount;
  const tenure = a.tenure_months;

  return (
    <Screen
      edges={['bottom']}
      onRefresh={() => app.refetch()}
      refreshing={app.isRefetching}
      footer={
        a.status === 'draft' ? (
          <Button title="Continue application" onPress={() => router.replace(`/apply/${a.id}`)} />
        ) : offerWaiting ? (
          <Button title="Review your offer" icon="arrow-forward" onPress={() => router.push(`/applications/${a.id}/offer`)} />
        ) : loan ? (
          <Button title="View your loan" icon="arrow-forward" onPress={() => router.push(`/loans/${loan.id}`)} />
        ) : null
      }>
      <Card style={{ gap: space.sm }}>
        <View style={styles.between}>
          <Text variant="heading" style={{ flex: 1 }}>
            {a.product_name}
          </Text>
          <Badge label={s.label} tone={s.tone} />
        </View>
        <Text variant="display">{naira(amount)}</Text>
        <Text variant="small" muted>
          {a.approved_amount && a.approved_amount !== a.requested_amount ? `Approved (you asked for ${naira(a.requested_amount)}) · ` : ''}
          {tenure ? `${tenure} month${tenure === 1 ? '' : 's'}` : ''}
          {a.repayment_cadence ? ` · ${CADENCE[a.repayment_cadence] ?? a.repayment_cadence} repayments` : ''}
        </Text>
        {trackIndex(a.status) >= 0 ? (
          <View style={{ marginTop: space.sm }}>
            <StatusTrack status={a.status} />
          </View>
        ) : null}
      </Card>

      {a.status === 'rejected' ? (
        <Card style={{ gap: space.xs, borderWidth: 1.5, borderColor: colors.error }}>
          <Text variant="heading">{s.hint}</Text>
          {a.rejection_reason ? (
            <Text variant="small" muted>
              Reason: {a.rejection_reason}
            </Text>
          ) : null}
          <Text variant="small" muted>
            You're welcome to apply again, or visit your branch to talk it through.
          </Text>
          <Button title="Start a new application" variant="secondary" size="sm" onPress={() => router.push('/apply')} />
        </Card>
      ) : offerWaiting ? (
        <Card style={{ gap: space.xs, borderWidth: 1.5, borderColor: colors.cyan }}>
          <Text variant="heading">{a.status === 'offer_sent' ? 'Your offer is ready' : 'Your loan is approved'}</Text>
          <Text variant="small" muted>
            Review the offer: the amount, interest, fees and every payment date. Accept to continue, or decline if
            the terms don't work for you.
          </Text>
          <Button
            title="Review offer"
            size="sm"
            onPress={() => router.push(`/applications/${a.id}/offer`)}
            style={{ alignSelf: 'flex-start', marginTop: space.xs }}
          />
        </Card>
      ) : (
        <Banner
          tone={needsDocs ? 'warning' : 'info'}
          message={
            needsDocs
              ? 'A document needs replacing. Tap it below to upload a new one.'
              : a.status === 'approved' && a.offer_accepted_at
                ? "You've accepted the offer. We're preparing your payout."
                : s.hint
          }
        />
      )}

      <SectionHeader title="Documents" />
      <DocumentChecklist application={a} editable="rejected" />

      <SectionHeader title="Details" />
      <Card style={{ gap: space.xs }}>
        <Detail label="Reference" value={a.id.slice(0, 8).toUpperCase()} />
        <Detail label="Submitted" value={dateTime(a.submitted_at)} />
        <Detail label="Branch" value={a.branch} />
        <Detail label="Pay-out account" value={bankLine(a.universal_form as Record<string, string>)} />
      </Card>
    </Screen>
  );
}

function bankLine(form: Record<string, string>) {
  const n = form?.bank_account_number;
  return n ? `${form.bank_name ?? 'Bank'} •••• ${String(n).slice(-4)}` : '—';
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.between}>
      <Text variant="small" muted>
        {label}
      </Text>
      <Text variant="small" style={{ flexShrink: 1, textAlign: 'right' }}>
        {value}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  between: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: space.sm },
});
