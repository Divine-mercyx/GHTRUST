import Ionicons from '@expo/vector-icons/Ionicons';
import { router, useFocusEffect, type Href } from 'expo-router';
import { useCallback, useMemo, useRef, useState } from 'react';
import { Linking, Pressable, StyleSheet, View } from 'react-native';
import Animated, { FadeInDown } from 'react-native-reanimated';

import type { ApplicationSummary } from '@/api/types';
import { useSession } from '@/auth/session';
import { ActionSheet, type SheetAction } from '@/components/ActionSheet';
import { Avatar } from '@/components/Avatar';
import { Card, Row, SectionHeader } from '@/components/Card';
import { BalanceCard, CircleAction } from '@/components/home/BalanceCard';
import { PressableScale } from '@/components/home/PressableScale';
import { TRANSACTION_ROW_HEIGHT, TransactionItem } from '@/components/home/TransactionItem';
import { Screen } from '@/components/Screen';
import { ErrorState, Skeleton } from '@/components/States';
import { Text } from '@/components/Text';
import { recentActivity } from '@/lib/activity';
import {
  useApplications,
  useFeatures,
  useInvestmentPlans,
  useLoans,
  useMe,
  useMyInvestments,
  useTransactions,
  useUnreadCount,
  useWallet,
} from '@/lib/queries';
import { colors, font, radius, shadow, space } from '@/theme/tokens';

const enter = (i: number) => FadeInDown.duration(380).delay(60 * i);

/**
 * Home: greeting bar, balance card with four round actions, what needs doing (offer,
 * documents, draft), a product banner, recent activity, and help links.
 */
export default function Home() {
  const { firstName } = useSession();
  const me = useMe();
  const loans = useLoans();
  const applications = useApplications();
  const features = useFeatures();
  const wallet = useWallet(features.wallet);
  const history = useTransactions(undefined, features.wallet);
  const plans = useInvestmentPlans();
  const investments = useMyInvestments();
  const unreadQuery = useUnreadCount();
  const unread = unreadQuery.data?.unread_count ?? 0;
  const [sheet, setSheet] = useState<'more' | 'contact' | null>(null);

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

  const loanList = loans.data?.items;
  const apps = applications.data?.items ?? [];
  const openLoans = useMemo(
    () =>
      (loanList ?? [])
        .filter((l) => l.status === 'active' || l.status === 'overdue')
        .sort((a, b) => (a.next_due_date ?? '9').localeCompare(b.next_due_date ?? '9')),
    [loanList],
  );
  const nextLoan = openLoans[0];
  const overdue = openLoans.some((l) => l.status === 'overdue');
  const nudge = pickNudge(apps);
  const activity = recentActivity(loanList ?? [], apps, history.data?.pages[0]?.items, 4);
  const expectedReturns = (investments.data ?? [])
    .filter((i) => i.status === 'active')
    .reduce((sum, i) => sum + Number(i.projected_return), 0);
  const bestRate = Math.max(0, ...(plans.data ?? []).map((p) => Number(p.return_rate)));

  const name = me.data?.first_name ?? firstName;
  const initials = `${(me.data?.first_name?.[0] ?? name?.[0] ?? 'G').toUpperCase()}${(me.data?.last_name?.[0] ?? '').toUpperCase()}`;
  const loading = loans.isPending || applications.isPending;
  const support = features.support;

  const refresh = () => {
    loans.refetch();
    applications.refetch();
    me.refetch();
    unreadQuery.refetch();
    investments.refetch();
    if (features.wallet) {
      wallet.refetch();
      history.refetch();
    }
  };

  // Wallet repayments need the wallet; without it the loan page explains how to pay.
  const repay = () =>
    router.push(nextLoan ? (features.wallet ? `/repay/${nextLoan.id}` : `/loans/${nextLoan.id}`) : '/loans');
  const open = (url: string) => Linking.openURL(url).catch(() => router.push('/support'));
  const moreActions: SheetAction[] = [
    { label: 'Apply for a loan', icon: 'add-circle-outline', onPress: () => router.push('/apply') },
    { label: 'My loans', icon: 'document-text-outline', onPress: () => router.push('/loans') },
    { label: 'Invest', icon: 'trending-up-outline', onPress: () => router.push('/invest') },
    ...(features.wallet
      ? [
          { label: 'Transactions', icon: 'receipt-outline' as const, onPress: () => router.push('/transactions') },
          { label: 'Bank account for withdrawals', icon: 'business-outline' as const, onPress: () => router.push('/payout-account') },
        ]
      : []),
  ];
  const contactActions: SheetAction[] = [
    ...(support?.whatsapp
      ? [{ label: 'WhatsApp', icon: 'logo-whatsapp' as const, onPress: () => open(`https://wa.me/${support.whatsapp}`) }]
      : []),
    ...(support?.phone ? [{ label: `Call ${support.phone}`, icon: 'call-outline' as const, onPress: () => open(`tel:${support.phone}`) }] : []),
    ...(support?.email ? [{ label: 'Email us', icon: 'mail-outline' as const, onPress: () => open(`mailto:${support.email}`) }] : []),
    { label: 'Send a message in the app', icon: 'chatbubbles-outline', onPress: () => router.push('/support/new') },
  ];

  const banner: Banner =
    features.investments && bestRate > 0
      ? {
          icon: 'trending-up',
          title: `Earn up to ${bestRate}% a year`,
          subtitle: 'Invest with fixed returns',
          href: '/invest',
        }
      : nextLoan && features.wallet
        ? { icon: 'flash', title: 'Pay ahead, finish sooner', subtitle: 'Repay any amount from your wallet', href: `/repay/${nextLoan.id}` }
        : { icon: 'rocket', title: 'Get a loan in minutes', subtitle: 'Business, payday, study and asset loans', href: '/apply' };

  return (
    <Screen onRefresh={refresh} refreshing={loans.isRefetching || applications.isRefetching}>
      <View style={styles.header}>
        <Text variant="title" numberOfLines={1} style={{ flex: 1 }}>
          Hi, <Text variant="title" style={{ fontFamily: font.extrabold }}>{name ?? 'there'}</Text>!
        </Text>
        <PressableScale
          accessibilityRole="button"
          accessibilityLabel={unread > 0 ? `Notifications, ${unread} unread` : 'Notifications'}
          onPress={() => router.push('/notifications')}
          style={styles.iconButton}>
          <Ionicons name="notifications-outline" size={22} color={colors.navy} />
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
              <Avatar profile={me.data} size={38} />
            ) : (
              <View style={styles.avatar}>
                <Text variant="small" color={colors.white} style={{ fontFamily: font.bold }}>
                  {initials}
                </Text>
              </View>
            )}
          </View>
        </PressableScale>
        <PressableScale
          accessibilityRole="button"
          accessibilityLabel="Settings"
          onPress={() => router.push('/security')}
          style={styles.iconButton}>
          <Ionicons name="settings-outline" size={22} color={colors.navy} />
        </PressableScale>
      </View>

      {loans.isError ? (
        <ErrorState error={loans.error} onRetry={() => loans.refetch()} />
      ) : loans.isPending ? (
        <CardSkeleton />
      ) : (
        <Animated.View entering={enter(0)}>
          <BalanceCard
            walletEnabled={features.wallet}
            wallet={wallet.data}
            walletFailed={wallet.isError}
            openLoans={openLoans}
            expectedReturns={expectedReturns}
          />
        </Animated.View>
      )}

      <Animated.View entering={enter(1)} style={styles.actions}>
        {features.wallet ? (
          <>
            <CircleAction icon="add" label="Add money" onPress={() => router.push('/fund')} />
            <CircleAction icon="arrow-up" label="Withdraw" onPress={() => router.push('/withdraw')} />
          </>
        ) : (
          <>
            <CircleAction icon="add" label="Apply" onPress={() => router.push('/apply')} />
            <CircleAction icon="document-text-outline" label="My loans" onPress={() => router.push('/loans')} />
          </>
        )}
        <CircleAction icon="card-outline" label="Repay" attention={overdue} onPress={repay} />
        <CircleAction icon="chevron-down" label="More" onPress={() => setSheet('more')} />
      </Animated.View>

      {nudge ? (
        <Animated.View entering={enter(2)}>
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

      <Animated.View entering={enter(3)}>
        <PressableScale
          scaleTo={0.98}
          accessibilityRole="button"
          accessibilityLabel={`${banner.title}. ${banner.subtitle}`}
          onPress={() => router.push(banner.href)}
          style={styles.banner}>
          <View pointerEvents="none" style={styles.bannerGlow} />
          <View style={styles.bannerIcon}>
            <Ionicons name={banner.icon} size={22} color={colors.white} />
          </View>
          <View style={{ flex: 1, gap: 2 }}>
            <Text variant="bodyStrong" color={colors.white} numberOfLines={1}>
              {banner.title}
            </Text>
            <Text variant="small" color="rgba(255,255,255,0.75)" numberOfLines={1}>
              {banner.subtitle}
            </Text>
          </View>
          <Ionicons name="chevron-forward" size={20} color={colors.white} />
        </PressableScale>
      </Animated.View>

      <Animated.View entering={enter(4)}>
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

      <Animated.View entering={enter(5)}>
        <Card style={styles.links}>
          <Row icon="help-buoy-outline" title="Help & support" onPress={() => router.push('/support')} />
          <Row icon="chatbubble-ellipses-outline" title="Contact us" onPress={() => setSheet('contact')} />
          <Row icon="lock-closed-outline" title="Privacy policy" onPress={() => router.push('/legal/privacy')} last />
        </Card>
      </Animated.View>

      <ActionSheet visible={sheet === 'more'} title="More" actions={moreActions} onClose={() => setSheet(null)} />
      <ActionSheet visible={sheet === 'contact'} title="Contact us" actions={contactActions} onClose={() => setSheet(null)} />
    </Screen>
  );
}

type Banner = { icon: keyof typeof Ionicons.glyphMap; title: string; subtitle: string; href: Href };

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
  const offer = apps.find((a) => a.status === 'offer_sent' || (a.status === 'approved' && !a.offer_accepted_at));
  if (offer) {
    return {
      href: `/applications/${offer.id}/offer`,
      icon: 'checkmark-circle-outline',
      iconColor: colors.yield,
      accent: colors.yield,
      title: offer.status === 'offer_sent' ? 'Your loan offer is ready' : 'Your loan is approved',
      subtitle: `${offer.product_name} · review your offer`,
    };
  }
  const docs = apps.find((a) => a.status === 'documents_incomplete');
  if (docs) {
    return {
      href: `/applications/${docs.id}`,
      icon: 'alert-circle-outline',
      iconColor: colors.pending,
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

/** Same footprint as the balance card, so nothing jumps when data arrives. */
function CardSkeleton() {
  return (
    <View style={styles.cardSkeleton} accessibilityLabel="Loading">
      <Skeleton height={12} width="35%" style={styles.onNavy} />
      <Skeleton height={36} width="60%" style={styles.onNavy} />
      <Skeleton height={22} width="45%" style={styles.onNavy} />
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
  header: { flexDirection: 'row', alignItems: 'center', gap: space.sm, marginBottom: space.xs },
  iconButton: {
    width: 42,
    height: 42,
    borderRadius: 21,
    backgroundColor: colors.card,
    alignItems: 'center',
    justifyContent: 'center',
    ...shadow,
  },
  bellBadge: {
    position: 'absolute',
    top: 4,
    right: 3,
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
    width: 46,
    height: 46,
    borderRadius: 23,
    borderWidth: 2,
    borderColor: colors.cyan,
    padding: 2,
    backgroundColor: colors.surface,
  },
  avatar: { flex: 1, borderRadius: 19, backgroundColor: colors.navy, alignItems: 'center', justifyContent: 'center' },
  cardSkeleton: { backgroundColor: colors.navy, borderRadius: radius.lg, padding: space.xl, gap: space.sm },
  onNavy: { backgroundColor: 'rgba(255,255,255,0.14)' },
  actions: { flexDirection: 'row', justifyContent: 'space-between', paddingHorizontal: space.xxs },
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
  banner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
    backgroundColor: colors.navySoft,
    borderRadius: radius.lg,
    padding: space.md,
    overflow: 'hidden',
    ...shadow,
  },
  bannerGlow: {
    position: 'absolute',
    right: -40,
    top: -50,
    width: 150,
    height: 150,
    borderRadius: 75,
    backgroundColor: colors.cyan,
    opacity: 0.22,
  },
  bannerIcon: {
    width: 44,
    height: 44,
    borderRadius: radius.md,
    backgroundColor: 'rgba(255,255,255,0.16)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  list: { backgroundColor: colors.card, borderRadius: radius.lg, overflow: 'hidden', ...shadow },
  links: { paddingVertical: space.xxs, marginTop: space.xs },
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
