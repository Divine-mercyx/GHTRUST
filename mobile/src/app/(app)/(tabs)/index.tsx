import Ionicons from '@expo/vector-icons/Ionicons';
import { router, useFocusEffect, type Href } from 'expo-router';
import { useCallback, useRef } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import Animated, { FadeInDown } from 'react-native-reanimated';

import type { ApplicationSummary } from '@/api/types';
import { useSession } from '@/auth/session';
import { Card, SectionHeader } from '@/components/Card';
import { Avatar } from '@/components/Avatar';
import { HeroCard } from '@/components/home/HeroCard';
import { PressableScale } from '@/components/home/PressableScale';
import { QuickActionButton } from '@/components/home/QuickActionButton';
import { TRANSACTION_ROW_HEIGHT, TransactionItem } from '@/components/home/TransactionItem';
import { Screen } from '@/components/Screen';
import { ErrorState, Skeleton } from '@/components/States';
import { Text } from '@/components/Text';
import { recentActivity } from '@/lib/activity';
import { greeting } from '@/lib/format';
import {
  useApplications,
  useFeatures,
  useLoans,
  useMe,
  useTransactions,
  useUnreadCount,
  useWallet,
} from '@/lib/queries';
import { colors, font, radius, shadow, space } from '@/theme/tokens';

const enter = (i: number) => FadeInDown.duration(380).delay(60 * i);

export default function Home() {
  const { firstName } = useSession();
  const me = useMe();
  const loans = useLoans();
  const applications = useApplications();
  const features = useFeatures();
  const wallet = useWallet(features.wallet);
  const history = useTransactions(undefined, features.wallet);
  const unreadQuery = useUnreadCount();
  const unread = unreadQuery.data?.unread_count ?? 0;

  // Tabs stay mounted, so coming back to Home (e.g. from the inbox or after money arrived)
  // wouldn't refetch on its own. The first focus is the initial load, so skip it.
  const focusedOnce = useRef(false);
  const refetchUnread = unreadQuery.refetch;
  const refetchWallet = wallet.refetch;
  const refetchHistory = history.refetch;
  const walletOn = features.wallet;
  useFocusEffect(
    useCallback(() => {
      if (!focusedOnce.current) {
        focusedOnce.current = true;
        return;
      }
      refetchUnread();
      if (walletOn) {
        refetchWallet();
        refetchHistory();
      }
    }, [refetchUnread, refetchWallet, refetchHistory, walletOn]),
  );

  const loanList = loans.data?.items ?? [];
  const apps = applications.data?.items ?? [];
  const openLoans = loanList.filter((l) => l.status === 'active' || l.status === 'overdue');
  const nextLoan = [...openLoans].sort((a, b) => (a.next_due_date ?? '9').localeCompare(b.next_due_date ?? '9'))[0];
  const overdue = openLoans.some((l) => l.status === 'overdue');
  const nudge = pickNudge(apps);
  const activity = recentActivity(loanList, apps, history.data?.pages[0]?.items);

  const name = me.data?.first_name ?? firstName;
  const initials = `${(me.data?.first_name?.[0] ?? name?.[0] ?? 'G').toUpperCase()}${(me.data?.last_name?.[0] ?? '').toUpperCase()}`;
  const loading = loans.isPending || applications.isPending;

  const refresh = () => {
    loans.refetch();
    applications.refetch();
    me.refetch();
    unreadQuery.refetch();
    if (features.wallet) {
      wallet.refetch();
      history.refetch();
    }
  };

  return (
    <Screen onRefresh={refresh} refreshing={loans.isRefetching || applications.isRefetching}>
      <View style={styles.header}>
        <View style={{ flex: 1 }}>
          <Text variant="small" muted>
            {greeting()}
          </Text>
          <Text variant="title" numberOfLines={1}>
            {name ?? 'Welcome'}
          </Text>
        </View>
        <PressableScale
          accessibilityRole="button"
          accessibilityLabel={unread > 0 ? `Notifications, ${unread} unread` : 'Notifications'}
          onPress={() => router.push('/notifications')}
          style={styles.bell}>
          <Ionicons name="notifications-outline" size={24} color={colors.navy} />
          {unread > 0 ? (
            <View style={styles.bellBadge}>
              <Text variant="small" color={colors.white} style={styles.bellCount}>
                {unread > 9 ? '9+' : unread}
              </Text>
            </View>
          ) : null}
        </PressableScale>
        <PressableScale accessibilityRole="button" accessibilityLabel="Profile" onPress={() => router.push('/profile')}>
          <View style={styles.avatarRing}>
            {me.data ? (
              <Avatar profile={me.data} size={44} />
            ) : (
              <View style={styles.avatar}>
                <Text variant="bodyStrong" color={colors.white} style={{ fontFamily: font.bold }}>
                  {initials}
                </Text>
              </View>
            )}
          </View>
        </PressableScale>
      </View>

      {loans.isError ? (
        <ErrorState error={loans.error} onRetry={() => loans.refetch()} />
      ) : loans.isPending ? (
        <HeroSkeleton />
      ) : (
        <Animated.View entering={enter(0)}>
          <HeroCard loan={nextLoan} openLoans={openLoans.length} wallet={wallet.data} walletEnabled={features.wallet} />
        </Animated.View>
      )}

      {nudge ? (
        <Animated.View entering={enter(1)}>
          <PressableScale
            scaleTo={0.98}
            accessibilityRole="button"
            onPress={() => router.push(nudge.href)}
            style={[styles.nudge, { borderLeftColor: nudge.accent }]}>
            <Ionicons name={nudge.icon} size={22} color={nudge.iconColor} />
            <View style={{ flex: 1 }}>
              <Text variant="bodyStrong" numberOfLines={1}>
                {nudge.title}
              </Text>
              <Text variant="small" muted numberOfLines={1}>
                {nudge.subtitle}
              </Text>
            </View>
            <Ionicons name="chevron-forward" size={18} color={colors.textFaint} />
          </PressableScale>
        </Animated.View>
      ) : null}

      <Animated.View entering={enter(2)}>
        <SectionHeader title="Quick actions" />
        <View style={styles.actions}>
          <QuickActionButton icon="add-circle" label="Apply for a loan" onPress={() => router.push('/apply')} />
          <QuickActionButton
            icon="document-text"
            label="My loans"
            attention={overdue}
            onPress={() => router.push('/loans')}
          />
          {features.wallet ? (
            <QuickActionButton icon="arrow-up-circle" label="Withdraw" onPress={() => router.push('/withdraw')} />
          ) : (
            <QuickActionButton icon="shield-checkmark" label="Security" onPress={() => router.push('/security')} />
          )}
          <QuickActionButton icon="help-buoy" label="Help & support" onPress={() => router.push('/support')} />
        </View>
      </Animated.View>

      <Animated.View entering={enter(3)}>
        <SectionHeader
          title="Recent activity"
          action={
            activity.length > 0 ? (
              <Pressable
                accessibilityRole="button"
                hitSlop={10}
                onPress={() => router.push(features.wallet ? '/transactions' : '/loans')}>
                <Text variant="small" color={colors.cyanDeep} style={{ fontFamily: font.semibold }}>
                  See all
                </Text>
              </Pressable>
            ) : undefined
          }
        />
        {loading ? (
          <ActivitySkeleton />
        ) : applications.isError ? (
          <ErrorState error={applications.error} onRetry={() => applications.refetch()} />
        ) : activity.length === 0 ? (
          <Card style={styles.empty}>
            <View style={styles.emptyIcon}>
              <Ionicons name="sparkles-outline" size={22} color={colors.cyanDeep} />
            </View>
            <Text variant="bodyStrong" align="center">
              Nothing here yet
            </Text>
            <Text variant="small" muted align="center">
              Your applications, payouts and repayments will show up here.
            </Text>
          </Card>
        ) : (
          <View style={styles.list}>
            {activity.map((item, i) => (
              <TransactionItem key={item.id} item={item} last={i === activity.length - 1} />
            ))}
          </View>
        )}
      </Animated.View>
    </Screen>
  );
}

type Nudge = {
  href: Href;
  icon: keyof typeof Ionicons.glyphMap;
  iconColor: string;
  accent: string;
  title: string;
  subtitle: string;
};

/** One nudge at most: a loan offer to accept, then documents to fix, then an unfinished draft. */
function pickNudge(apps: ApplicationSummary[]): Nudge | null {
  const offer = apps.find((a) => a.status === 'approved' && !a.offer_accepted_at);
  if (offer) {
    return {
      href: `/applications/${offer.id}/offer`,
      icon: 'checkmark-circle-outline',
      iconColor: colors.success,
      accent: colors.success,
      title: 'Your loan is approved',
      subtitle: `${offer.product_name} · review your offer`,
    };
  }
  const docs = apps.find((a) => a.status === 'documents_incomplete');
  if (docs) {
    return {
      href: `/applications/${docs.id}`,
      icon: 'alert-circle-outline',
      iconColor: colors.warning,
      accent: colors.warningRaw,
      title: 'Some documents need attention',
      subtitle: `${docs.product_name} · tap to fix and re-upload`,
    };
  }
  const draft = apps.find((a) => a.status === 'draft');
  if (draft) {
    return {
      href: `/apply/${draft.id}`,
      icon: 'create-outline',
      iconColor: colors.cyanDeep,
      accent: colors.cyan,
      title: 'Finish your application',
      subtitle: `${draft.product_name} · tap to continue`,
    };
  }
  return null;
}

/** Same footprint as the hero, so nothing jumps when data arrives. */
function HeroSkeleton() {
  return (
    <View style={styles.heroSkeleton} accessibilityLabel="Loading">
      <Skeleton height={12} width="35%" style={styles.onNavy} />
      <Skeleton height={34} width="60%" style={styles.onNavy} />
      <Skeleton height={14} width="80%" style={styles.onNavy} />
      <Skeleton height={48} style={styles.onNavyButton} />
    </View>
  );
}

function ActivitySkeleton() {
  return (
    <View style={styles.list}>
      {[0, 1, 2].map((i) => (
        <View key={i} style={[styles.skeletonRow, i < 2 && styles.skeletonDivider]}>
          <Skeleton height={42} width={42} style={styles.skeletonIcon} />
          <View style={{ flex: 1, gap: 6 }}>
            <Skeleton height={14} width="70%" />
            <Skeleton height={12} width="45%" />
          </View>
          <Skeleton height={14} width={64} />
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: 'row', alignItems: 'center', gap: space.md, marginBottom: space.xs },
  bell: {
    width: 46,
    height: 46,
    borderRadius: 23,
    backgroundColor: colors.card,
    alignItems: 'center',
    justifyContent: 'center',
    ...shadow,
  },
  bellBadge: {
    position: 'absolute',
    top: 6,
    right: 5,
    minWidth: 18,
    height: 18,
    paddingHorizontal: 4,
    borderRadius: 9,
    backgroundColor: colors.error,
    borderWidth: 2,
    borderColor: colors.card,
    alignItems: 'center',
    justifyContent: 'center',
  },
  bellCount: { fontSize: 10, lineHeight: 12, fontFamily: font.bold },
  avatarRing: {
    width: 52,
    height: 52,
    borderRadius: 26,
    borderWidth: 2,
    borderColor: colors.cyan,
    padding: 2,
    backgroundColor: colors.surface,
  },
  avatar: { flex: 1, borderRadius: 22, backgroundColor: colors.navy, alignItems: 'center', justifyContent: 'center' },
  heroSkeleton: { backgroundColor: colors.navy, borderRadius: radius.xl - 4, padding: space.xl, gap: space.sm },
  onNavy: { backgroundColor: 'rgba(255,255,255,0.14)' },
  onNavyButton: { backgroundColor: 'rgba(255,255,255,0.14)', marginTop: space.sm, borderRadius: radius.md },
  nudge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    padding: space.md,
    borderLeftWidth: 4,
    borderLeftColor: colors.cyan,
    ...shadow,
  },
  actions: { flexDirection: 'row', gap: space.sm },
  list: { backgroundColor: colors.card, borderRadius: radius.lg, overflow: 'hidden', ...shadow },
  skeletonRow: {
    height: TRANSACTION_ROW_HEIGHT,
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
    paddingHorizontal: space.md,
  },
  skeletonIcon: { borderRadius: radius.md },
  skeletonDivider: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  empty: { alignItems: 'center', gap: space.xs, paddingVertical: space.xl },
  emptyIcon: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: colors.mint,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: space.xs,
  },
});
