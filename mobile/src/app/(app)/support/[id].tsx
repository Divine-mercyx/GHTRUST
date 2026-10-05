import Ionicons from '@expo/vector-icons/Ionicons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, TextInput, View } from 'react-native';

import { support } from '@/api/endpoints';
import { messageFor } from '@/api/errors';
import type { SupportMessage, SupportTicket } from '@/api/types';
import { Badge } from '@/components/Badge';
import { Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { Banner, CardSkeleton, ErrorState } from '@/components/States';
import { Text } from '@/components/Text';
import { dateTime } from '@/lib/format';
import { keys, useTicket } from '@/lib/queries';
import { useSupportChat } from '@/lib/supportSocket';
import { CATEGORY, ticketStatus } from '@/lib/support';
import { colors, font, radius, space } from '@/theme/tokens';

const MAX_LENGTH = 2000;

/** Older servers send one message and one reply instead of the conversation. */
function conversation(t: SupportTicket): SupportMessage[] {
  if (t.messages?.length) return t.messages;
  const out: SupportMessage[] = [
    { id: 'first', author: 'customer', author_name: 'You', body: t.message, created_at: t.created_at },
  ];
  if (t.reply) {
    out.push({ id: 'reply', author: 'staff', author_name: 'GH Trust support', body: t.reply, created_at: t.replied_at ?? t.created_at });
  }
  return out;
}

/**
 * One support request as a live conversation with the team: messages arrive instantly over
 * the chat socket, with typing and "Seen". When the socket is down, replies go over HTTP.
 */
export default function SupportRequest() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const queryClient = useQueryClient();
  const ticket = useTicket(id);
  const chat = useSupportChat(id);
  const [draft, setDraft] = useState('');

  const send = useMutation({
    mutationFn: async (body: string) => {
      try {
        await chat.send(body);
        return null;
      } catch {
        return support.reply(id, body); // not connected: the HTTP route does the same
      }
    },
    onSuccess: (updated) => {
      setDraft('');
      if (updated) queryClient.setQueryData(keys.ticket(id), updated);
      queryClient.invalidateQueries({ queryKey: keys.tickets });
    },
  });

  // Seeing the team's replies marks them read (they see "Seen").
  const unread = ticket.data?.messages?.some((m) => m.author === 'staff' && !m.read_at) ?? false;
  const { live, read } = chat;
  useEffect(() => {
    if (!unread) return;
    if (live) read();
    else
      support
        .read(id)
        .then((t) => queryClient.setQueryData(keys.ticket(id), t))
        .catch(() => undefined);
  }, [unread, live, read, id, queryClient]);

  const t = ticket.data;
  if (ticket.isPending) {
    return (
      <Screen edges={['bottom']}>
        <CardSkeleton lines={4} />
      </Screen>
    );
  }
  if (ticket.isError || !t) {
    return (
      <Screen edges={['bottom']}>
        <ErrorState error={ticket.error} onRetry={() => ticket.refetch()} />
      </Screen>
    );
  }

  const s = ticketStatus(t.status);
  const messages = conversation(t);
  const text = draft.trim();
  const canSend = text.length > 0 && !send.isPending;
  const lastMine = [...messages].reverse().find((m) => m.author === 'customer');

  return (
    <Screen
      edges={['bottom']}
      stickToEnd
      onRefresh={() => ticket.refetch()}
      refreshing={ticket.isRefetching}
      footer={
        <View style={{ gap: space.xs }}>
          {send.error ? <Banner message={messageFor(send.error)} /> : null}
          {t.status === 'resolved' ? (
            <Text variant="small" muted>
              This request is resolved. Writing again reopens it.
            </Text>
          ) : null}
          <View style={styles.composer}>
            <TextInput
              value={draft}
              onChangeText={(v) => {
                setDraft(v);
                if (v.trim()) chat.typing();
              }}
              placeholder="Write a reply"
              placeholderTextColor={colors.textFaint}
              multiline
              maxLength={MAX_LENGTH}
              editable={!send.isPending}
              style={styles.input}
              accessibilityLabel="Your reply"
            />
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Send reply"
              accessibilityState={{ disabled: !canSend, busy: send.isPending }}
              disabled={!canSend}
              onPress={() => send.mutate(text)}
              style={[styles.send, !canSend && { opacity: 0.4 }]}>
              {send.isPending ? (
                <ActivityIndicator color={colors.white} />
              ) : (
                <Ionicons name="send" size={18} color={colors.white} />
              )}
            </Pressable>
          </View>
        </View>
      }>
      <View style={styles.head}>
        <View style={{ flex: 1, gap: 2 }}>
          <Text variant="heading">{CATEGORY[t.category]?.label ?? 'Request'}</Text>
          <Text variant="small" muted>
            {t.reference} · {dateTime(t.created_at)}
          </Text>
        </View>
        <Badge label={s.label} tone={s.tone} />
      </View>

      {messages.map((m) =>
        m.author === 'customer' ? (
          <View key={m.id} style={[styles.bubble, styles.mine]}>
            <Text variant="small" style={{ lineHeight: 21 }}>
              {m.body}
            </Text>
            <View style={styles.metaRow}>
              <Text variant="small" muted style={styles.meta}>
                {dateTime(m.created_at)}
              </Text>
              {m.id === lastMine?.id ? (
                m.read_at ? (
                  <Text variant="small" color={colors.cyanDeep} style={styles.meta}>
                    Seen
                  </Text>
                ) : (
                  <Ionicons name="checkmark" size={13} color={colors.textFaint} accessibilityLabel="Sent" />
                )
              ) : null}
            </View>
          </View>
        ) : (
          <View key={m.id} style={styles.replyRow}>
            <View style={styles.avatar}>
              <Ionicons name="headset" size={16} color={colors.white} />
            </View>
            <View style={[styles.bubble, styles.theirs]}>
              <Text variant="small" style={{ lineHeight: 21 }}>
                {m.body}
              </Text>
              <Text variant="small" muted style={styles.meta}>
                {m.author_name} · {dateTime(m.created_at)}
              </Text>
            </View>
          </View>
        ),
      )}

      {chat.staffTyping ? (
        <View style={styles.replyRow} accessibilityLabel="GH Trust support is typing">
          <View style={styles.avatar}>
            <Ionicons name="headset" size={16} color={colors.white} />
          </View>
          <View style={[styles.bubble, styles.theirs, styles.typing]}>
            <View style={styles.dot} />
            <View style={[styles.dot, { opacity: 0.6 }]} />
            <View style={[styles.dot, { opacity: 0.3 }]} />
          </View>
        </View>
      ) : null}

      {!chat.staffTyping && (t.awaiting_reply ?? !t.reply) ? (
        <Card>
          <Text variant="small" muted>
            We've received your message and will reply here. You'll get a notification when we do.
          </Text>
        </Card>
      ) : null}

      {t.status === 'resolved' ? (
        <Pressable accessibilityRole="link" onPress={() => router.push('/support/new')} hitSlop={8}>
          <Text variant="small" color={colors.cyanDeep} align="center" style={{ fontFamily: font.semibold }}>
            Something else? Start a new request
          </Text>
        </Pressable>
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  head: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  bubble: { padding: space.md, borderRadius: radius.lg, gap: space.xs, maxWidth: '88%' },
  mine: { alignSelf: 'flex-end', backgroundColor: '#E4F3FA', borderBottomRightRadius: 6 },
  theirs: { backgroundColor: colors.card, borderBottomLeftRadius: 6, flexShrink: 1 },
  meta: { fontSize: 11 },
  metaRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'flex-end', gap: 6 },
  typing: { flexDirection: 'row', alignItems: 'center', gap: 5, paddingVertical: 14 },
  dot: { width: 7, height: 7, borderRadius: 4, backgroundColor: colors.slate },
  replyRow: { flexDirection: 'row', alignItems: 'flex-end', gap: space.xs },
  avatar: {
    width: 30,
    height: 30,
    borderRadius: 15,
    backgroundColor: colors.navy,
    alignItems: 'center',
    justifyContent: 'center',
  },
  composer: { flexDirection: 'row', alignItems: 'flex-end', gap: space.sm },
  input: {
    flex: 1,
    minHeight: 46,
    maxHeight: 120,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.lg,
    backgroundColor: colors.card,
    paddingHorizontal: space.md,
    paddingTop: 12,
    paddingBottom: 12,
    fontFamily: font.medium,
    fontSize: 15,
    color: colors.text,
  },
  send: {
    width: 46,
    height: 46,
    borderRadius: 23,
    backgroundColor: colors.navy,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
