import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { memo, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import type { Loan, Wallet } from '@/api/types';
import { Skeleton } from '@/components/States';
import { Text } from '@/components/Text';
import { daysUntil, naira, relativeDue } from '@/lib/format';
import { colors, font, radius, shadow, space } from '@/theme/tokens';

import { PressableScale } from './PressableScale';

const MUTED = 'rgba(255,255,255,0.72)';
const FAINT = 'rgba(255,255,255,0.14)';

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

type Pill = { label: string; icon: keyof typeof Ionicons.glyphMap; fg: string; bg: string; onPress?: () => void };

/**
 * The navy balance card at the top of Home. With the wallet on it shows the wallet
 * balance (and what's owed on loans underneath); without it, the loan balance.
 * The pill says what matters next: an overdue or upcoming repayment, else returns.
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
  const next = openLoans[0];
  const showWallet = walletEnabled;
  const value = showWallet ? wallet?.available_balance : owed;
  const today = new Date().toLocaleDateString('en-NG', { day: 'numeric', month: 'short', year: 'numeric' });

  return (
    <View style={styles.card} accessibilityLabel={showWallet ? 'Wallet balance' : 'Loan balance'}>
      <View pointerEvents="none" style={[styles.glow, styles.glowTop]} />
      <View pointerEvents="none" style={[styles.glow, styles.glowBottom]} />

      <View style={styles.between}>
        <Text variant="small" color={MUTED}>
          {showWallet ? 'Wallet balance' : 'Loan balance'}
        </Text>
        <Text variant="small" color={MUTED}>
          {today}
        </Text>
      </View>

      <View style={styles.balanceRow}>
        {value === undefined && walletFailed ? (
          <Text variant="title" color={MUTED}>
            Couldn't load · pull to refresh
          </Text>
        ) : value === undefined ? (
          <Skeleton height={36} width={170} style={styles.skeleton} />
        ) : (
          <Text variant="display" color={colors.white} numberOfLines={1} adjustsFontSizeToFit style={{ flexShrink: 1 }}>
            {hidden ? '₦ • • • • •' : naira(value, { kobo: showWallet })}
          </Text>
        )}
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={hidden ? 'Show balance' : 'Hide balance'}
          hitSlop={12}
          onPress={() => setHidden((h) => !h)}>
          <Ionicons name={hidden ? 'eye-off-outline' : 'eye-outline'} size={22} color={MUTED} />
        </Pressable>
      </View>

      <View style={styles.between}>
        <StatusPill pill={pillFor(next, expectedReturns, hidden, walletEnabled)} />
        {showWallet && owed > 0 ? (
          <Pressable accessibilityRole="button" hitSlop={8} onPress={() => router.push('/loans')}>
            <Text variant="small" color={MUTED}>
              Loan {hidden ? '₦ • • •' : naira(owed)} <Ionicons name="chevron-forward" size={12} color={MUTED} />
            </Text>
          </Pressable>
        ) : null}
      </View>
    </View>
  );
});

function pillFor(next: Loan | undefined, expectedReturns: number, hidden: boolean, walletEnabled: boolean): Pill {
  if (next?.next_due_date) {
    const days = daysUntil(next.next_due_date);
    // Wallet repayments need the wallet; without it the loan page explains how to pay.
    const repay = () => router.push(walletEnabled ? `/repay/${next.id}` : `/loans/${next.id}`);
    if (next.status === 'overdue' || days < 0) {
      return { label: relativeDue(next.next_due_date), icon: 'alert-circle', fg: '#FFD5D5', bg: 'rgba(207,46,46,0.35)', onPress: repay };
    }
    const amount = hidden ? '' : `${naira(next.monthly_payment)} · `;
    if (days <= 3) {
      return { label: `${amount}${relativeDue(next.next_due_date)}`, icon: 'time', fg: '#FFE2A8', bg: 'rgba(229,175,89,0.28)', onPress: repay };
    }
    return { label: `${amount}${relativeDue(next.next_due_date)}`, icon: 'calendar', fg: colors.yieldBright, bg: 'rgba(94,224,176,0.18)', onPress: repay };
  }
  if (expectedReturns > 0) {
    return {
      label: `+${hidden ? '₦ • • •' : naira(expectedReturns)} expected`,
      icon: 'trending-up',
      fg: colors.yieldBright,
      bg: 'rgba(94,224,176,0.18)',
      onPress: () => router.push('/invest'),
    };
  }
  return { label: 'No repayments due', icon: 'checkmark-circle', fg: colors.yieldBright, bg: 'rgba(94,224,176,0.18)' };
}

function StatusPill({ pill }: { pill: Pill }) {
  const body = (
    <View style={[styles.pill, { backgroundColor: pill.bg }]}>
      <Ionicons name={pill.icon} size={14} color={pill.fg} />
      <Text variant="small" color={pill.fg} style={styles.pillText} numberOfLines={1}>
        {pill.label}
      </Text>
    </View>
  );
  if (!pill.onPress) return body;
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={pill.label} onPress={pill.onPress} hitSlop={6}>
      {body}
    </Pressable>
  );
}

export type CircleActionProps = {
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  onPress: () => void;
  /** Small red dot when something here needs attention. */
  attention?: boolean;
};

/** Round white button with a label underneath, for the row under the balance card. */
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

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.navy,
    borderRadius: radius.lg,
    padding: space.xl,
    gap: space.sm,
    overflow: 'hidden',
    ...shadow,
  },
  // Soft brand glows instead of a gradient image or library.
  glow: { position: 'absolute', borderRadius: 999 },
  glowTop: { width: 240, height: 240, top: -130, right: -90, backgroundColor: colors.cyan, opacity: 0.2 },
  glowBottom: { width: 200, height: 200, bottom: -130, left: -70, backgroundColor: colors.navySoft, opacity: 0.9 },
  between: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: space.sm },
  balanceRow: { flexDirection: 'row', alignItems: 'center', gap: space.sm, minHeight: 44 },
  skeleton: { backgroundColor: FAINT },
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: radius.pill,
    maxWidth: 230,
  },
  pillText: { fontFamily: font.semibold, fontSize: 12, lineHeight: 16 },
  action: { flex: 1, alignItems: 'center', gap: space.xs },
  circle: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: colors.card,
    alignItems: 'center',
    justifyContent: 'center',
    ...shadow,
  },
  dot: {
    position: 'absolute',
    top: 4,
    right: 4,
    width: 11,
    height: 11,
    borderRadius: 6,
    backgroundColor: colors.error,
    borderWidth: 2,
    borderColor: colors.card,
  },
  actionLabel: { fontSize: 12, lineHeight: 16, color: colors.text, fontFamily: font.semibold },
});
