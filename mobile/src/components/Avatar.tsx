import { Image, StyleSheet, View } from 'react-native';

import type { Profile } from '@/api/types';
import { usePhoto } from '@/lib/queries';
import { colors, font } from '@/theme/tokens';

import { Text } from './Text';

/** The customer's photo (the one they chose, else their BVN photo), or their initials. */
export function Avatar({ profile, size = 72, ring = false }: { profile: Profile | undefined; size?: number; ring?: boolean }) {
  const photo = usePhoto(profile?.photo_version, !!profile);
  const image = photo.data?.image;
  const initials = profile ? `${profile.first_name[0] ?? ''}${profile.last_name[0] ?? ''}` : '';
  const box = { width: size, height: size, borderRadius: size / 2 };

  return (
    <View
      accessibilityRole="image"
      accessibilityLabel={image ? 'Your profile photo' : `Initials ${initials}`}
      style={[styles.circle, box, ring && styles.ring]}>
      {image ? (
        <Image source={{ uri: `data:${photo.data?.content_type ?? 'image/jpeg'};base64,${image}` }} style={box} />
      ) : (
        <Text style={{ fontFamily: font.bold, fontSize: size * 0.32, color: colors.white }}>{initials}</Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  circle: { backgroundColor: colors.navy, alignItems: 'center', justifyContent: 'center', overflow: 'hidden' },
  ring: { borderWidth: 3, borderColor: colors.cyan },
});
