import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { Button } from '@/components/Button';
import { SectionHeader } from '@/components/Card';
import { ApplicationCard, LoanCard } from '@/components/loans';
import { Screen } from '@/components/Screen';
import { CardSkeleton, EmptyState, ErrorState } from '@/components/States';
import { Text } from '@/components/Text';
import { useApplications, useLoans } from '@/lib/queries';
import { isClosedApplication } from '@/lib/status';
import { colors, font, radius } from '@/theme/tokens';

type Tab = 'loans' | 'applications';

export default function LoansTab() {
  const [tab, setTab] = useState<Tab>('loans');
  const loans = useLoans();
  const applications = useApplications();

  const allLoans = loans.data?.items ?? [];
  const open = allLoans.filter((l) => l.status === 'active' || l.status === 'overdue');
  const closed = allLoans.filter((l) => !open.includes(l));
  const apps = applications.data?.items ?? [];
  const activeApps = apps.filter((a) => !isClosedApplication(a.status));
  const pastApps = apps.filter((a) => isClosedApplication(a.status));

  const query = tab === 'loans' ? loans : applications;

  return (
    <Screen
      onRefresh={() => query.refetch()}
      refreshing={query.isRefetching}>
      <View style={styles.header}>
        <Text variant="title">Loans</Text>
        <Button title="Apply" icon="add" size="sm" onPress={() => router.push('/apply')} />
      </View>

      <View style={styles.segment} accessibilityRole="tablist">
        {(['loans', 'applications'] as const).map((t) => {
          const selected = tab === t;
          const count = t === 'loans' ? open.length : activeApps.length;
          return (
            <Pressable
              key={t}
              accessibilityRole="tab"
              accessibilityState={{ selected }}
              onPress={() => setTab(t)}
              style={[styles.segmentItem, selected && styles.segmentActive]}>
              <Text variant="small" color={selected ? colors.navy : colors.textMuted} style={{ fontFamily: font.bold }}>
                {t === 'loans' ? 'My loans' : 'Applications'}
                {count ? ` (${count})` : ''}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {query.isPending ? (
        <>
          <CardSkeleton />
          <CardSkeleton />
        </>
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => query.refetch()} />
      ) : tab === 'loans' ? (
        allLoans.length === 0 ? (
          <EmptyState
            icon="cash-outline"
            title="No loans yet"
            body="When an application is approved and paid out, your loan and repayment schedule appear here."
            action={{ title: 'Apply for a loan', onPress: () => router.push('/apply') }}
          />
        ) : (
          <>
            {open.map((l) => (
              <LoanCard key={l.id} loan={l} />
            ))}
            {closed.length ? <SectionHeader title="Closed" /> : null}
            {closed.map((l) => (
              <LoanCard key={l.id} loan={l} />
            ))}
          </>
        )
      ) : apps.length === 0 ? (
        <EmptyState
          icon="document-text-outline"
          title="No applications"
          body="Start an application and you can save it and finish later."
          action={{ title: 'Start an application', onPress: () => router.push('/apply') }}
        />
      ) : (
        <>
          {activeApps.map((a) => (
            <ApplicationCard key={a.id} app={a} />
          ))}
          {pastApps.length ? <SectionHeader title="Past applications" /> : null}
          {pastApps.map((a) => (
            <ApplicationCard key={a.id} app={a} />
          ))}
        </>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  segment: { flexDirection: 'row', backgroundColor: colors.surfaceNav, borderRadius: radius.md, padding: 4 },
  segmentItem: { flex: 1, minHeight: 40, borderRadius: radius.sm, alignItems: 'center', justifyContent: 'center' },
  segmentActive: { backgroundColor: colors.card, boxShadow: '0 1px 3px rgba(27,47,107,0.12)' },
});
