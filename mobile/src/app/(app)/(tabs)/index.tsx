import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { Linking, Pressable, StyleSheet, View } from 'react-native';
import Animated, { FadeInDown } from 'react-native-reanimated';

import type { Loan } from '@/api/types';
import { useSession } from '@/auth/session';
import { Button } from '@/components/Button';
import { Card, SectionHeader } from '@/components/Card';
import { ApplicationCard, productName, StatusTrack } from '@/components/loans';
import { Screen } from '@/components/Screen';
import { CardSkeleton, ErrorState } from '@/components/States';
import { Text } from '@/components/Text';
import { greeting, naira, relativeDue } from '@/lib/format';
import { useApplications, useFeatures, useLoans, useMe, useWallet } from '@/lib/queries';
import { applicationStatus, isClosedApplication } from '@/lib/status';
import { colors, HIT, radius, space } from '@/theme/tokens';

export default function Home() {
  const { firstName } = useSession();
  const me = useMe();
  const loans = useLoans();
  const applications = useApplications();
  const features = useFeatures();
  const wallet = useWallet(features.wallet);

  const openLoans = (loans.data?.items ?? []).filter((l) => l.status === 'active' || l.status === 'overdue');
  const nextLoan = [...openLoans].sort((a, b) => (a.next_due_date ?? '9').localeCompare(b.next_due_date ?? '9'))[0];
  const apps = applications.data?.items ?? [];
  const drafts = apps.filter((a) => a.status === 'draft');
  const inFlight = apps.filter((a) => a.status !== 'draft' && !isClosedApplication(a.status));
  const name = me.data?.first_name ?? firstName;

  const refreshing = loans.isRefetching || applications.isRefetching;
  const refresh = () => {
    loans.refetch();
    applications.refetch();
    me.refetch();
    if (features.wallet) wallet.refetch();
  };

  return (
    <Screen onRefresh={refresh} refreshing={refreshing}>
      <View style={styles.header}>
        <View style={{ flex: 1 }}>
          <Text variant="small" muted>
            {greeting()}
          </Text>
          <Text variant="title" numberOfLines={1}>
            {name ?? 'Welcome'}
          </Text>
        </View>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Profile"
          onPress={() => router.push('/profile')}
          style={styles.avatar}>
          <Text variant="bodyStrong" color={colors.white}>
            {(me.data?.first_name?.[0] ?? name?.[0] ?? 'G').toUpperCase()}
            {(me.data?.last_name?.[0] ?? '').toUpperCase()}
          </Text>
        </Pressable>
      </View>

      {loans.isPending ? (
        <CardSkeleton lines={2} />
      ) : loans.isError ? (
        <ErrorState error={loans.error} onRetry={() => loans.refetch()} />
      ) : (
        <Animated.View entering={FadeInDown.duration(350)}>
          <Hero loan={nextLoan} count={openLoans.length} walletEnabled={features.wallet} />
        </Animated.View>
      )}

      {features.wallet ? (
        <Card style={styles.walletRow}>
          {/* Two separate targets: nesting a button inside a pressable card breaks screen readers. */}
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`Wallet balance ${wallet.data ? naira(wallet.data.available_balance) : ''}`}
            onPress={() => router.push('/wallet')}
            style={({ pressed }) => [styles.walletInfo, pressed && { opacity: 0.7 }]}>
            <View style={styles.walletIcon}>
              <Ionicons name="wallet" size={20} color={colors.cyanDeep} />
            </View>
            <View style={{ flex: 1 }}>
              <Text variant="small" muted>
                Wallet balance
              </Text>
              <Text variant="heading">{wallet.data ? naira(wallet.data.available_balance) : '—'}</Text>
            </View>
          </Pressable>
          <Button title="Add money" size="sm" variant="secondary" icon="add" onPress={() => router.push('/fund')} />
        </Card>
      ) : null}

      {drafts.length > 0 ? (
        <>
          <SectionHeader title="Pick up where you left off" />
          {drafts.slice(0, 2).map((a) => (
            <ApplicationCard key={a.id} app={a} />
          ))}
        </>
      ) : null}

      {inFlight.length > 0 ? (
        <>
          <SectionHeader title="Application progress" />
          {inFlight.slice(0, 2).map((a) => {
            const s = applicationStatus(a.status);
            return (
              <Card key={a.id} onPress={() => router.push(`/applications/${a.id}`)} accessibilityLabel={`${a.product_name}, ${s.label}`}>
                <View style={styles.between}>
                  <Text variant="heading">{a.product_name}</Text>
                  <Text variant="bodyStrong">{naira(a.approved_amount ?? a.requested_amount)}</Text>
                </View>
                <Text variant="small" muted style={{ marginTop: 2, marginBottom: space.md }}>
                  {s.hint}
                </Text>
                <StatusTrack status={a.status} />
              </Card>
            );
          })}
        </>
      ) : null}

      <SectionHeader title="Quick actions" />
      <View style={styles.actions}>
        <Action icon="add-circle" label="Apply for a loan" onPress={() => router.push('/apply')} />
        <Action icon="document-text" label="My loans" onPress={() => router.push('/loans')} />
        {features.support?.phone ? (
          <Action icon="call" label="Call support" onPress={() => Linking.openURL(`tel:${features.support?.phone}`)} />
        ) : (
          <Action icon="phone-portrait" label="My devices" onPress={() => router.push('/devices')} />
        )}
      </View>
    </Screen>
  );
}

function Hero({ loan, count, walletEnabled }: { loan?: Loan; count: number; walletEnabled: boolean }) {
  if (!loan) {
    return (
      <View style={[styles.hero, { gap: space.sm }]}>
        <Text variant="caption" color={colors.cyan}>
          GH TRUST LOANS
        </Text>
        <Text variant="title" color={colors.white}>
          Get the funds your plans need
        </Text>
        <Text variant="small" color="rgba(255,255,255,0.75)">
          Business, payday, study and asset loans. Apply in minutes and track every step here.
        </Text>
        <Button
          title="Start an application"
          icon="arrow-forward"
          onPress={() => router.push('/apply')}
          style={{ backgroundColor: colors.cyan, marginTop: space.xs }}
        />
      </View>
    );
  }
  const overdue = loan.status === 'overdue';
  return (
    <View style={styles.hero}>
      <View style={styles.between}>
        <Text variant="caption" color={overdue ? '#FFB3B3' : colors.cyan}>
          {overdue ? 'PAYMENT OVERDUE' : 'NEXT REPAYMENT'}
        </Text>
        <Text variant="small" color="rgba(255,255,255,0.7)">
          {productName(loan.product_type)}
          {count > 1 ? ` · +${count - 1} more` : ''}
        </Text>
      </View>
      <Text variant="display" color={colors.white} style={{ marginTop: space.xs }}>
        {naira(loan.monthly_payment)}
      </Text>
      <Text variant="small" color={overdue ? '#FFB3B3' : 'rgba(255,255,255,0.8)'}>
        {loan.next_due_date ? relativeDue(loan.next_due_date) : 'No payment scheduled'}
      </Text>
      <View style={styles.heroDivider} />
      <View style={styles.between}>
        <View>
          <Text variant="small" color="rgba(255,255,255,0.7)">
            Outstanding
          </Text>
          <Text variant="heading" color={colors.white}>
            {naira(loan.outstanding)}
          </Text>
        </View>
        <Button
          title={walletEnabled ? 'Repay now' : 'View loan'}
          size="sm"
          icon={walletEnabled ? 'flash' : 'arrow-forward'}
          onPress={() => router.push(walletEnabled ? `/repay/${loan.id}` : `/loans/${loan.id}`)}
          style={{ backgroundColor: colors.cyan, borderColor: colors.cyan }}
        />
      </View>
    </View>
  );
}

function Action({ icon, label, onPress }: { icon: keyof typeof Ionicons.glyphMap; label: string; onPress: () => void }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={onPress}
      style={({ pressed }) => [styles.action, pressed && { opacity: 0.85, transform: [{ scale: 0.98 }] }]}>
      <View style={styles.actionIcon}>
        <Ionicons name={icon} size={22} color={colors.navy} />
      </View>
      <Text variant="small" align="center" style={{ fontSize: 12 }} numberOfLines={2}>
        {label}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: 'row', alignItems: 'center', gap: space.md, marginBottom: space.xs },
  avatar: {
    width: HIT,
    height: HIT,
    borderRadius: HIT / 2,
    backgroundColor: colors.navy,
    alignItems: 'center',
    justifyContent: 'center',
  },
  between: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: space.sm },
  hero: { backgroundColor: colors.navy, borderRadius: radius.xl, padding: space.xl },
  heroDivider: { height: StyleSheet.hairlineWidth, backgroundColor: 'rgba(255,255,255,0.2)', marginVertical: space.lg },
  walletRow: { flexDirection: 'row', alignItems: 'center', gap: space.sm, paddingVertical: space.md },
  walletInfo: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: space.sm, minHeight: HIT },
  walletIcon: {
    width: 40,
    height: 40,
    borderRadius: radius.md,
    backgroundColor: colors.mint,
    alignItems: 'center',
    justifyContent: 'center',
  },
  actions: { flexDirection: 'row', gap: space.sm },
  action: {
    flex: 1,
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    paddingVertical: space.md,
    paddingHorizontal: space.xs,
    alignItems: 'center',
    gap: space.xs,
    minHeight: 96,
  },
  actionIcon: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: colors.surfaceNav,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
