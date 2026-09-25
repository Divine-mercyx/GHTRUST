/**
 * GH Trust design tokens (see docs/mobile-app-handoff.md → Brand).
 * Every colour, size and radius in the app comes from here.
 */
import { Platform, type TextStyle, type ViewStyle } from 'react-native';

export const colors = {
  navy: '#1B2F6B',
  navySoft: '#2A4185',
  cyan: '#2FA4D7',
  cyanDeep: '#1E8BBB',
  mint: '#E9F8F9',
  surface: '#F4F7FB',
  surfaceNav: '#EEF2F9',
  card: '#FFFFFF',
  success: '#00A86B',
  successBg: '#E6F6EF',
  warning: '#C98A1E',
  warningBg: '#FCF3E3',
  warningRaw: '#E5AF59',
  error: '#CF2E2E',
  errorBg: '#FBEAEA',
  gold: '#B58838',
  text: '#1B2F6B',
  textMuted: '#5B6B8C',
  textFaint: '#8C99B5',
  border: '#E1E7F2',
  borderStrong: '#C9D3E6',
  overlay: 'rgba(15, 26, 60, 0.45)',
  white: '#FFFFFF',
} as const;

export const space = { xxs: 4, xs: 8, sm: 12, md: 16, lg: 20, xl: 24, xxl: 32, xxxl: 48 } as const;

export const radius = { sm: 10, md: 14, lg: 20, xl: 28, pill: 999 } as const;

export const font = {
  regular: 'Montserrat_400Regular',
  medium: 'Montserrat_500Medium',
  semibold: 'Montserrat_600SemiBold',
  bold: 'Montserrat_700Bold',
  extrabold: 'Montserrat_800ExtraBold',
} as const;

type Variant = Pick<TextStyle, 'fontFamily' | 'fontSize' | 'lineHeight' | 'letterSpacing'>;

export const type = {
  display: { fontFamily: font.extrabold, fontSize: 32, lineHeight: 38, letterSpacing: -0.6 },
  title: { fontFamily: font.bold, fontSize: 22, lineHeight: 28, letterSpacing: -0.3 },
  heading: { fontFamily: font.bold, fontSize: 17, lineHeight: 22 },
  body: { fontFamily: font.medium, fontSize: 15, lineHeight: 22 },
  bodyStrong: { fontFamily: font.semibold, fontSize: 15, lineHeight: 22 },
  small: { fontFamily: font.medium, fontSize: 13, lineHeight: 18 },
  caption: { fontFamily: font.semibold, fontSize: 11, lineHeight: 14, letterSpacing: 0.6 },
} satisfies Record<string, Variant>;

export type TypeVariant = keyof typeof type;

/** Soft navy-tinted card shadow from the brand spec. */
export const shadow: ViewStyle = Platform.select({
  ios: {
    shadowColor: colors.navy,
    shadowOpacity: 0.08,
    shadowRadius: 16,
    shadowOffset: { width: 0, height: 6 },
  },
  android: { elevation: 2 },
  default: { boxShadow: '0 1px 3px rgba(27,47,107,.06), 0 8px 24px rgba(27,47,107,.06)' },
}) as ViewStyle;

/** Minimum touch target (Apple HIG 44pt / Material 48dp). */
export const HIT = 48;
