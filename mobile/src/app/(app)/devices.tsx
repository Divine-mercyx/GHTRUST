import Ionicons from '@expo/vector-icons/Ionicons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { StyleSheet, View } from 'react-native';

import { auth } from '@/api/endpoints';
import { messageFor } from '@/api/errors';
import { Badge } from '@/components/Badge';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { Banner, CardSkeleton, ErrorState } from '@/components/States';
import { Text } from '@/components/Text';
import { confirm } from '@/lib/confirm';
import { dateTime } from '@/lib/format';
import { keys, useSessions } from '@/lib/queries';
import { colors, radius, space } from '@/theme/tokens';

export default function Devices() {
  const sessions = useSessions();
  const queryClient = useQueryClient();
  const revoke = useMutation({
    mutationFn: (id: string) => auth.revokeSession(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.sessions }),
  });

  const list = [...(sessions.data ?? [])].sort((a, b) => Number(!!b.current) - Number(!!a.current));

  return (
    <Screen edges={['bottom']} onRefresh={() => sessions.refetch()} refreshing={sessions.isRefetching}>
      <Text muted>
        These devices are signed in to your account. Remove any you don't recognise; they'll need a new code to sign in.
      </Text>
      {revoke.error ? <Banner message={messageFor(revoke.error)} /> : null}
      {sessions.isPending ? (
        <CardSkeleton lines={2} />
      ) : sessions.isError ? (
        <ErrorState error={sessions.error} onRetry={() => sessions.refetch()} />
      ) : (
        list.map((s) => (
          <Card key={s.id} style={styles.card}>
            <View style={styles.icon}>
              <Ionicons
                name={s.platform === 'ios' || s.platform === 'android' ? 'phone-portrait-outline' : 'desktop-outline'}
                size={20}
                color={colors.navy}
              />
            </View>
            <View style={{ flex: 1, gap: 2 }}>
              <Text variant="bodyStrong" numberOfLines={1}>
                {s.device_name || 'Unknown device'}
              </Text>
              <Text variant="small" muted>
                Last active {dateTime(s.last_used_at)}
              </Text>
              {s.current ? <Badge label="This device" tone="success" /> : null}
            </View>
            {!s.current ? (
              <Button
                title="Remove"
                size="sm"
                variant="danger"
                loading={revoke.isPending && revoke.variables === s.id}
                onPress={() =>
                  confirm('Remove device?', `${s.device_name || 'This device'} will be signed out.`, 'Remove', () =>
                    revoke.mutate(s.id),
                  )
                }
              />
            ) : null}
          </Card>
        ))
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  card: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  icon: {
    width: 40,
    height: 40,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceNav,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
