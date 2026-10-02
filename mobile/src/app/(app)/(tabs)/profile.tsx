import Ionicons from '@expo/vector-icons/Ionicons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';

import { auth } from '@/api/endpoints';
import { messageFor } from '@/api/errors';
import type { Profile as ProfileData } from '@/api/types';
import { APP_VERSION } from '@/api/config';
import { useSession } from '@/auth/session';
import { ActionSheet, type SheetAction } from '@/components/ActionSheet';
import { Avatar } from '@/components/Avatar';
import { Button } from '@/components/Button';
import { Card, Row, SectionHeader } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { Banner, CardSkeleton, ErrorState } from '@/components/States';
import { Text } from '@/components/Text';
import { PhotoError, pickProfilePhoto } from '@/features/profilePhoto';
import { confirm } from '@/lib/confirm';
import { date, humanize } from '@/lib/format';
import { keys, useMe } from '@/lib/queries';
import { colors, font, space } from '@/theme/tokens';

export default function Profile() {
  const me = useMe();
  const { signOut } = useSession();
  const queryClient = useQueryClient();
  const p = me.data;
  const [sheet, setSheet] = useState(false);
  const [photoError, setPhotoError] = useState<string | null>(null);

  const savePhoto = useMutation({
    mutationFn: (change: { image: string } | { remove: true }) =>
      'remove' in change ? auth.removePhoto() : auth.setPhoto(change.image),
    onSuccess: (profile: ProfileData) => {
      setPhotoError(null);
      queryClient.setQueryData(keys.me, profile);
    },
    onError: (e) => setPhotoError(messageFor(e)),
  });

  const choose = (source: 'camera' | 'library') =>
    pickProfilePhoto(source)
      .then((image) => image && savePhoto.mutate({ image }))
      .catch((e) => setPhotoError(e instanceof PhotoError ? e.message : "We couldn't open your photos. Try again."));

  const photoActions: SheetAction[] = [
    { label: 'Take a photo', icon: 'camera-outline', onPress: () => choose('camera') },
    { label: 'Choose from photos', icon: 'images-outline', onPress: () => choose('library') },
    ...(p?.has_custom_photo
      ? [{ label: 'Use my BVN photo', icon: 'finger-print-outline' as const, onPress: () => savePhoto.mutate({ remove: true }) }]
      : []),
  ];

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
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Change profile photo"
              disabled={savePhoto.isPending}
              onPress={() => setSheet(true)}
              style={styles.avatarWrap}>
              <Avatar profile={p} size={84} />
              <View style={styles.cameraBadge}>
                {savePhoto.isPending ? (
                  <ActivityIndicator size="small" color={colors.white} />
                ) : (
                  <Ionicons name="camera" size={14} color={colors.white} />
                )}
              </View>
            </Pressable>
            <Text variant="heading" align="center">
              {p.full_name}
            </Text>
            <Text variant="small" muted align="center">
              Account {p.account_number} · {p.branch}
            </Text>
          </Card>
          {photoError ? <Banner message={photoError} /> : null}
          <ActionSheet visible={sheet} title="Profile photo" actions={photoActions} onClose={() => setSheet(false)} />

          <SectionHeader
            title="Personal details"
            action={
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Edit contact details"
                hitSlop={10}
                onPress={() => router.push('/edit-contact')}>
                <Text variant="small" color={colors.cyanDeep} style={{ fontFamily: font.semibold }}>
                  Edit
                </Text>
              </Pressable>
            }
          />
          <Card style={styles.list}>
            <Row icon="call-outline" title="Phone" subtitle={p.phone} />
            <Row icon="mail-outline" title="Email" subtitle={p.email || 'Not provided'} />
            <Row icon="finger-print-outline" title="BVN" subtitle={p.bvn_masked} />
            <Row icon="calendar-outline" title="Date of birth" subtitle={p.date_of_birth ? date(p.date_of_birth) : 'Not provided'} />
            <Row icon="home-outline" title="Address" subtitle={p.residential_address || 'Not provided'} />
            <Row icon="shield-checkmark-outline" title="Account status" subtitle={humanize(p.status)} last />
          </Card>
          <Text variant="small" muted style={{ paddingHorizontal: space.xs }}>
            Your name, BVN, date of birth, phone and photo come from your BVN record. You can change your photo,
            email and address; to change the rest, visit a branch.
          </Text>
        </>
      )}

      <SectionHeader title="Security" />
      <Card style={styles.list}>
        <Row
          icon="shield-checkmark-outline"
          title="Security"
          subtitle="PINs, Face ID / fingerprint"
          onPress={() => router.push('/security')}
        />
        <Row icon="phone-portrait-outline" title="Signed-in devices" subtitle="See and remove devices" onPress={() => router.push('/devices')} last />
      </Card>

      <SectionHeader title="Help & legal" />
      <Card style={styles.list}>
        <Row
          icon="help-buoy-outline"
          title="Help & support"
          subtitle="Questions, contact us, report a problem"
          onPress={() => router.push('/support')}
        />
        <Row icon="document-text-outline" title="Terms of Use" onPress={() => router.push('/legal/terms')} />
        <Row icon="lock-closed-outline" title="Privacy Policy" onPress={() => router.push('/legal/privacy')} last />
      </Card>

      <SectionHeader title="Account" />
      <Card style={styles.list}>
        <Row
          icon="trash-outline"
          iconColor={colors.error}
          iconBg={colors.errorBg}
          title="Delete account"
          subtitle="Permanently delete your account and personal data"
          onPress={() => router.push('/delete-account')}
          last
        />
      </Card>

      <View style={{ gap: space.sm, marginTop: space.xl }}>
        <Button
          title="Sign out"
          variant="secondary"
          icon="log-out-outline"
          onPress={() => confirm('Sign out?', 'You can sign back in on this phone with your PIN.', 'Sign out', () => signOut())}
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
  avatarWrap: { marginBottom: space.sm },
  cameraBadge: {
    position: 'absolute',
    right: -2,
    bottom: -2,
    width: 30,
    height: 30,
    borderRadius: 15,
    backgroundColor: colors.cyanDeep,
    borderWidth: 2,
    borderColor: colors.card,
    alignItems: 'center',
    justifyContent: 'center',
  },
  list: { paddingVertical: space.xs },
});
