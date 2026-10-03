import { ImageManipulator, SaveFormat } from 'expo-image-manipulator';
import * as ImagePicker from 'expo-image-picker';

import { withLockPaused } from '@/auth/lockPolicy';

export class PhotoError extends Error {}

const SIZE = 512; // square, plenty for an avatar and small to upload

/** Pick or take a square photo and shrink it to a small JPEG (base64), or null if cancelled. */
export async function pickProfilePhoto(source: 'camera' | 'library'): Promise<string | null> {
  if (source === 'camera') {
    const permission = await withLockPaused(() => ImagePicker.requestCameraPermissionsAsync());
    if (!permission.granted) throw new PhotoError('Camera access is off. Allow it in Settings, or choose a photo instead.');
  }
  const options: ImagePicker.ImagePickerOptions = {
    mediaTypes: ['images'],
    allowsEditing: true, // lets the customer crop to a square around their face
    aspect: [1, 1],
    quality: 1,
    exif: false,
  };
  const res = await withLockPaused(() =>
    source === 'camera' ? ImagePicker.launchCameraAsync(options) : ImagePicker.launchImageLibraryAsync(options),
  );
  const asset = res.canceled ? null : res.assets?.[0];
  if (!asset) return null;

  const context = ImageManipulator.manipulate(asset.uri);
  context.resize({ width: SIZE, height: SIZE });
  const image = await context.renderAsync();
  const saved = await image.saveAsync({ format: SaveFormat.JPEG, compress: 0.8, base64: true });
  if (!saved.base64) throw new PhotoError("We couldn't read that photo. Try another one.");
  return saved.base64;
}
