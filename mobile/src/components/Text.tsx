import { Text as RNText, type TextProps } from 'react-native';

import { colors, type as typeScale, type TypeVariant } from '@/theme/tokens';

type Props = TextProps & {
  variant?: TypeVariant;
  color?: string;
  muted?: boolean;
  align?: 'left' | 'center' | 'right';
};

export function Text({ variant = 'body', color, muted, align, style, ...rest }: Props) {
  return (
    <RNText
      maxFontSizeMultiplier={1.6}
      style={[typeScale[variant], { color: color ?? (muted ? colors.textMuted : colors.text), textAlign: align }, style]}
      {...rest}
    />
  );
}
