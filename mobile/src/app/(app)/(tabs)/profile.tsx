import { router } from 'expo-router';
import { Linking, StyleSheet, View } from 'react-native';

import { APP_VERSION } from '@/api/config';
import { useSession } from '@/auth/session';
import { Button } from '@/components/Button';
import { Card, Row, SectionHeader } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { CardSkeleton, ErrorState } from '@/components/States';
import { Text } from '@/components/Text';
import { confirm } from '@/lib/confirm';
import { date, humanize } from '@/lib/format';
import { useFeatures, useMe } from '@/lib/queries';
import { colors, space } from '@/theme/tokens';

export default function Profile() {
  const me = useMe();
  const { signOut } = useSession();
  const { support } = useFeatures();
  const p = me.data;

  return (
    <Screen onRefresh={() => me.refetch()} refreshing={me.isRefetching}>
      <Text variant="title">Profile</Text>

      {me.isPending ? (
        <CardSkeleton lines={4} />
      ) : me.isError || !p ? (
        <ErrorState error={me.error} onRetry={() => me.refetch()} />
      ) : (
        <>
          <Card style={styles.identity}>
            <View style={styles.avatar}>
              <Text variant="title" color={colors.white}>
                {p.first_name[0]}
                {p.last_name[0]}
              </Text>
            </View>
            <Text variant="heading" align="center">
              {p.full_name}
            </Text>
            <Text variant="small" muted align="center">
              Account {p.account_number} · {p.branch}
            </Text>
          </Card>

          <SectionHeader title="Personal details" />
          <Card style={styles.list}>
            <Row icon="call-outline" title="Phone" subtitle={p.phone} />
            <Row icon="mail-outline" title="Email" subtitle={p.email || 'Not provided'} />
            <Row icon="finger-print-outline" title="BVN" subtitle={p.bvn_masked} />
            <Row icon="calendar-outline" title="Date of birth" subtitle={p.date_of_birth ? date(p.date_of_birth) : 'Not provided'} />
            <Row icon="home-outline" title="Address" subtitle={p.residential_address || 'Not provided'} />
            <Row icon="shield-checkmark-outline" title="Account status" subtitle={humanize(p.status)} last />
          </Card>
          <Text variant="small" muted style={{ paddingHorizontal: space.xs }}>
            These details come from your BVN record. To change them, visit your branch.
          </Text>
        </>
      )}

      <SectionHeader title="Security" />
      <Card style={styles.list}>
        <Row icon="phone-portrait-outline" title="Signed-in devices" subtitle="See and remove devices" onPress={() => router.push('/devices')} last />
      </Card>

      {support?.phone || support?.email ? (
        <>
          <SectionHeader title="Help" />
          <Card style={styles.list}>
            {support.phone ? (
              <Row
                icon="call-outline"
                title="Call us"
                subtitle={support.phone}
                onPress={() => Linking.openURL(`tel:${support.phone}`)}
                last={!support.email}
              />
            ) : null}
            {support.email ? (
              <Row icon="mail-outline" title="Email us" subtitle={support.email} onPress={() => Linking.openURL(`mailto:${support.email}`)} last />
            ) : null}
          </Card>
        </>
      ) : null}

      <View style={{ gap: space.sm, marginTop: space.xl }}>
        <Button
          title="Sign out"
          variant="secondary"
          icon="log-out-outline"
          onPress={() => confirm('Sign out?', "You'll need a code sent to your phone to sign in again.", 'Sign out', () => signOut())}
        />
        <Button
          title="Sign out of all devices"
          variant="ghost"
          onPress={() =>
            confirm(
              'Sign out everywhere?',
              'This signs you out on every phone where GH Trust is signed in, including this one.',
              'Sign out all',
              () => signOut({ everywhere: true }),
            )
          }
        />
      </View>
      <Text variant="small" muted align="center">
        GH Trust v{APP_VERSION}
      </Text>
    </Screen>
  );
}

const styles = StyleSheet.create({
  identity: { alignItems: 'center', gap: 4, paddingVertical: space.xl },
  avatar: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: colors.navy,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: space.sm,
  },
  list: { paddingVertical: space.xs },
});
