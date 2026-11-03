import colors from '@/constants/colors';

/**
 * Returns the design tokens for the current color scheme.
 *
 * SignalForge is a dark-first developer tool. The dark palette is the
 * product identity. On native, app.json `userInterfaceStyle: "dark"`
 * enforces this system-wide. On web (where useColorScheme reads the
 * browser OS preference), we return dark unconditionally so the preview
 * matches the intended design.
 */
export function useColors() {
  return { ...colors.dark, radius: colors.radius };
}
