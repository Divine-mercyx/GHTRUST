import Ionicons from '@expo/vector-icons/Ionicons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { ActivityIndicator, Platform, Pressable, StyleSheet, View } from 'react-native';

import { loans } from '@/api/endpoints';
import { messageFor } from '@/api/errors';
import type { Application, ChecklistItem } from '@/api/types';
import { ActionSheet } from '@/components/ActionSheet';
import { Badge } from '@/components/Badge';
import { Card } from '@/components/Card';
import { Banner } from '@/components/States';
import { Text } from '@/components/Text';
import { keys } from '@/lib/queries';
import { DOCUMENT_STATUS } from '@/lib/status';
import { colors, HIT, radius, space } from '@/theme/tokens';

import { pickFile, PickError, type Source } from './upload';

type Props = {
  application: Application;
  /** Only rejected documents can be replaced after submission. */
  editable: 'all' | 'rejected';
};

export function DocumentChecklist({ application, editable }: Props) {
  const queryClient = useQueryClient();
  const [target, setTarget] = useState<ChecklistItem | null>(null);
  const [pickError, setPickError] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: async ({ item, source }: { item: ChecklistItem; source: Source }) => {
      const file = await pickFile(source);
      if (!file) return null;
      return loans.uploadDocument(application.id, item.document_type, file);
    },
    onMutate: () => setPickError(null),
    onSuccess: (updated) => {
      if (updated) queryClient.setQueryData(keys.application(application.id), updated);
    },
    onError: (err) => setPickError(err instanceof PickError ? err.message : messageFor(err)),
  });

  const rejectedNotes = new Map(application.documents.filter((d) => d.status === 'rejected').map((d) => [d.document_type, d.rejection_note]));
  const done = application.document_checklist.filter((d) => d.uploaded && d.status !== 'rejected').length;
  const total = application.document_checklist.length;
  const sources: { label: string; icon: 'camera-outline' | 'images-outline' | 'document-outline'; source: Source }[] = [
    ...(Platform.OS === 'web' ? [] : [{ label: 'Take a photo', icon: 'camera-outline' as const, source: 'camera' as const }]),
    { label: 'Choose a photo', icon: 'images-outline', source: 'library' },
    { label: 'Choose a PDF or file', icon: 'document-outline', source: 'file' },
  ];

  return (
    <View style={{ gap: space.sm }}>
      <Text variant="small" muted>
        {done} of {total} uploaded
      </Text>
      {pickError ? <Banner message={pickError} /> : null}
      <Card style={{ paddingVertical: space.xs }}>
        {application.document_checklist.map((item, i) => {
          const status = item.status ? DOCUMENT_STATUS[item.status] : null;
          const rejected = item.status === 'rejected';
          const canEdit = editable === 'all' ? item.status !== 'verified' : rejected;
          const busy = upload.isPending && upload.variables?.item.document_type === item.document_type;
          const note = rejectedNotes.get(item.document_type);
          return (
            <Pressable
              key={item.document_type}
              disabled={!canEdit || upload.isPending}
              accessibilityRole="button"
              accessibilityLabel={`${item.label}, ${status?.label ?? 'not uploaded'}`}
              accessibilityHint={canEdit ? 'Upload this document' : undefined}
              onPress={() => setTarget(item)}
              style={({ pressed }) => [styles.row, i < total - 1 && styles.divider, pressed && { opacity: 0.7 }]}>
              <View style={[styles.icon, item.uploaded && !rejected && { backgroundColor: colors.successBg }, rejected && { backgroundColor: colors.errorBg }]}>
                <Ionicons
                  name={rejected ? 'alert' : item.uploaded ? 'checkmark' : 'cloud-upload-outline'}
                  size={18}
                  color={rejected ? colors.error : item.uploaded ? colors.success : colors.textMuted}
                />
              </View>
              <View style={{ flex: 1, gap: 2 }}>
                <Text variant="bodyStrong">{item.label}</Text>
                {rejected && note ? (
                  <Text variant="small" color={colors.error}>
                    {note}
                  </Text>
                ) : status?.hint ? (
                  <Text variant="small" muted>
                    {status.hint}
                  </Text>
                ) : !item.uploaded ? (
                  <Text variant="small" color={colors.cyanDeep}>
                    Tap to upload
                  </Text>
                ) : null}
              </View>
              {busy ? <ActivityIndicator color={colors.navy} /> : status ? <Badge label={status.label} tone={status.tone} /> : null}
            </Pressable>
          );
        })}
      </Card>

      <ActionSheet
        visible={!!target}
        title={target?.label ?? ''}
        onClose={() => setTarget(null)}
        actions={sources.map((s) => ({
          label: s.label,
          icon: s.icon,
          onPress: () => target && upload.mutate({ item: target, source: s.source }),
        }))}
      />
    </View>
  );
}

export const documentsComplete = (app: Application) =>
  app.document_checklist.every((d) => d.uploaded && d.status !== 'rejected');

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: space.sm, paddingVertical: space.sm, minHeight: HIT + 12 },
  divider: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  icon: {
    width: 36,
    height: 36,
    borderRadius: radius.sm,
    backgroundColor: colors.surfaceNav,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
