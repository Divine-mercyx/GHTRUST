import * as DocumentPicker from 'expo-document-picker';
import { ImageManipulator, SaveFormat } from 'expo-image-manipulator';
import * as ImagePicker from 'expo-image-picker';

export type UploadFile = { uri: string; name: string; type: string };
export type Source = 'camera' | 'library' | 'file';

const MAX_BYTES = 10 * 1024 * 1024; // API limit
const LONG_EDGE = 1800; // readable for staff, small enough for mobile data

export class PickError extends Error {}

/** Re-encode camera/library photos as JPEG: smaller, and the API checks content type. */
async function compress(uri: string, width: number, height: number): Promise<UploadFile> {
  const context = ImageManipulator.manipulate(uri);
  if (Math.max(width, height) > LONG_EDGE) {
    context.resize(width >= height ? { width: LONG_EDGE, height: null } : { width: null, height: LONG_EDGE });
  }
  const image = await context.renderAsync();
  const saved = await image.saveAsync({ format: SaveFormat.JPEG, compress: 0.72 });
  return { uri: saved.uri, name: `photo-${Date.now()}.jpg`, type: 'image/jpeg' };
}

/** Returns null when the customer cancels. */
export async function pickFile(source: Source): Promise<UploadFile | null> {
  if (source === 'file') {
    const res = await DocumentPicker.getDocumentAsync({
      type: ['application/pdf', 'image/jpeg', 'image/png'],
      copyToCacheDirectory: true,
      multiple: false,
    });
    if (res.canceled || !res.assets?.[0]) return null;
    const a = res.assets[0];
    if (a.size && a.size > MAX_BYTES) throw new PickError('That file is larger than 10 MB. Choose a smaller file.');
    const type = a.mimeType ?? (a.name.toLowerCase().endsWith('.pdf') ? 'application/pdf' : 'image/jpeg');
    if (type.startsWith('image/')) return compress(a.uri, 4000, 4000).catch(() => ({ uri: a.uri, name: a.name, type }));
    return { uri: a.uri, name: a.name, type };
  }

  if (source === 'camera') {
    const permission = await ImagePicker.requestCameraPermissionsAsync();
    if (!permission.granted) {
      throw new PickError('Camera access is off. Allow it in Settings, or choose a photo instead.');
    }
  }
  const options: ImagePicker.ImagePickerOptions = { mediaTypes: ['images'], quality: 1, allowsEditing: false, exif: false };
  const res = source === 'camera' ? await ImagePicker.launchCameraAsync(options) : await ImagePicker.launchImageLibraryAsync(options);
  if (res.canceled || !res.assets?.[0]) return null;
  const a = res.assets[0];
  return compress(a.uri, a.width, a.height);
}
