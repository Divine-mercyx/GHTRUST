import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { memo, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import type { Loan, Wallet } from '@/api/types';
import { NavyCard, ON_NAVY } from '@/components/NavyCard';
import { Skeleton } from '@/components/States';
import { Text } from '@/components/Text';
import { daysUntil, naira, relativeDue } from '@/lib/format';
import { colors, font, radius, space } from '@/theme/tokens';

import { PressableScale } from './PressableScale';

type Props = {
  walletEnabled: boolean;
  /** Undefined while loading. */
  wallet?: Wallet;
  /** The wallet couldn't be loaded (pull to refresh retries). */
  walletFailed?: boolean;
  /** Open (active or overdue) loans; the soonest due first. */
  openLoans: Loan[];
  /** Returns expected from active investments, if any. */
  expectedReturns: number;
};

type Pill = { label: string; icon: keyof typeof Ionicons.glyphMap; urgent?: boolean; onPress?: () => void };

/**
 * The navy balance card at the top of Home. With the wallet on it shows the wallet
 * balance (and what's owed on loans underneath); without it, the loan balance.
 * The gold pill on its edge says what matters next: a repayment, returns, or adding money.
 */
export const BalanceCard = memo(function BalanceCard({
  walletEnabled,
  wallet,
  walletFailed,
  openLoans,
  expectedReturns,
}: Props) {
  const [hidden, setHidden] = useState(false);
  const owed = openLoans.reduce((sum, l) => sum + Number(l.outstanding || 0), 0);
  const value = walletEnabled ? wallet?.available_balance : owed;
  const pill = pillFor(openLoans[0], expectedReturns, hidden, walletEnabled);

  return (
    <View style={styles.wrap}>
      <NavyCard accessibilityLabel={walletEnabled ? 'Available balance' : 'Loan balance'} style={styles.card}>
        <Text variant="small" color={ON_NAVY.muted}>
          {walletEnabled ? 'Available balance' : 'Loan balance'}
        </Text>

        <View style={styles.balanceRow}>
          {value === undefined && walletFailed ? (
            <Text variant="title" color={ON_NAVY.muted}>
              Couldn't load · pull to refresh
            </Text>
          ) : value === undefined ? (
            <Skeleton height={40} width={190} style={{ backgroundColor: ON_NAVY.faint }} />
          ) : (
            <Text variant="display" color={colors.white} numberOfLines={1} adjustsFontSizeToFit style={styles.amount}>
              {hidden ? '₦ • • • • •' : naira(value, { kobo: walletEnabled })}
            </Text>
          )}
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={hidden ? 'Show balance' : 'Hide balance'}
            hitSlop={12}
            onPress={() => setHidden((h) => !h)}>
            <Ionicons name={hidden ? 'eye-off-outline' : 'eye-outline'} size={22} color={ON_NAVY.muted} />
          </Pressable>
        </View>

        {walletEnabled && owed > 0 ? (
          <Pressable accessibilityRole="button" hitSlop={8} onPress={() => router.push('/loans')} style={styles.owed}>
            <Text variant="small" color={ON_NAVY.muted}>
              Loan balance {hidden ? '₦ • • •' : naira(owed)}
            </Text>
            <Ionicons name="chevron-forward" size={12} color={ON_NAVY.muted} />
          </Pressable>
        ) : (
          <View style={styles.owedSpacer} />
        )}
      </NavyCard>

      {pill ? <FloatingPill pill={pill} /> : null}
    </View>
  );
});

function pillFor(next: Loan | undefined, expectedReturns: number, hidden: boolean, walletEnabled: boolean): Pill | null {
  if (next?.next_due_date) {
    const days = daysUntil(next.next_due_date);
    // Wallet repayments need the wallet; without it the loan page explains how to pay.
    const repay = () => router.push(walletEnabled ? `/repay/${next.id}` : `/loans/${next.id}`);
    const amount = hidden ? '' : `${naira(next.monthly_payment)} · `;
    if (next.status === 'overdue' || days < 0) {
      return { label: relativeDue(next.next_due_date), icon: 'alert-circle', urgent: true, onPress: repay };
    }
    return { label: `${amount}${relativeDue(next.next_due_date)}`, icon: days <= 3 ? 'time' : 'calendar', onPress: repay };
  }
  if (expectedReturns > 0) {
    return {
      label: `+${hidden ? '₦ • • •' : naira(expectedReturns)} expected`,
      icon: 'trending-up',
      onPress: () => router.push('/invest'),
    };
  }
  if (walletEnabled) return { label: 'Add money', icon: 'add', onPress: () => router.push('/fund') };
  return null;
}

function FloatingPill({ pill }: { pill: Pill }) {
  const fg = pill.urgent ? colors.white : colors.navy;
  return (
    <PressableScale
      accessibilityRole="button"
      accessibilityLabel={pill.label}
      onPress={pill.onPress}
      disabled={!pill.onPress}
      style={[styles.pill, pill.urgent && styles.pillUrgent]}>
      <Ionicons name={pill.icon} size={16} color={fg} />
      <Text variant="small" color={fg} style={styles.pillText} numberOfLines={1}>
        {pill.label}
      </Text>
    </PressableScale>
  );
}

export type CircleActionProps = {
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  onPress: () => void;
  /** Small red dot when something here needs attention. */
  attention?: boolean;
};

/** One quick action in the Operations card: a round icon badge with its label underneath. */
export const CircleAction = memo(function CircleAction({ icon, label, onPress, attention }: CircleActionProps) {
  return (
    <PressableScale
      accessibilityRole="button"
      accessibilityLabel={attention ? `${label}, needs attention` : label}
      onPress={onPress}
      style={styles.action}>
      <View style={styles.circle}>
        <Ionicons name={icon} size={22} color={colors.navy} />
        {attention ? <View style={styles.dot} /> : null}
      </View>
      <Text variant="small" align="center" numberOfLines={1} style={styles.actionLabel}>
        {label}
      </Text>
    </PressableScale>
  );
});

const PILL_HEIGHT = 40;

const styles = StyleSheet.create({
  // Room under the card for the pill that sits on its edge.
  wrap: { paddingBottom: PILL_HEIGHT / 2 },
  card: { paddingBottom: space.xl + space.xs },
  balanceRow: { flexDirection: 'row', alignItems: 'center', gap: space.sm, minHeight: 48 },
  amount: { flexShrink: 1, fontSize: 36, lineHeight: 44 },
  owed: { flexDirection: 'row', alignItems: 'center', gap: 4, alignSelf: 'flex-start' },
  owedSpacer: { height: 18 },
  pill: {
    position: 'absolute',
    right: space.lg,
    bottom: 0,
    height: PILL_HEIGHT,
    maxWidth: '78%',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: space.md,
    borderRadius: radius.pill,
    backgroundColor: colors.highlight,
    borderWidth: 3,
    borderColor: colors.surface,
  },
  pillUrgent: { backgroundColor: colors.error },
  pillText: { fontFamily: font.bold, fontSize: 13, lineHeight: 16, flexShrink: 1 },
  action: { flex: 1, alignItems: 'center', gap: space.xs },
  circle: {
    width: 54,
    height: 54,
    borderRadius: 27,
    backgroundColor: colors.surfaceNav,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  dot: {
    position: 'absolute',
    top: 3,
    right: 3,
    width: 11,
    height: 11,
    borderRadius: 6,
    backgroundColor: colors.error,
    borderWidth: 2,
    borderColor: colors.card,
  },
  actionLabel: { fontSize: 12, lineHeight: 16, color: colors.text, fontFamily: font.semibold },
});
