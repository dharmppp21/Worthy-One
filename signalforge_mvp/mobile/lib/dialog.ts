import { Alert, Platform } from 'react-native';

/**
 * react-native-web ships `Alert.alert` as a literal no-op:
 *
 *   class Alert { static alert() {} }
 *
 * So on web every dialog silently did nothing — confirmations never appeared,
 * their onPress never fired (Sign Out did nothing at all), and error reports
 * vanished. These wrappers fall back to the browser's own dialogs.
 *
 * Reached through `globalThis` rather than `window` because the TS config here
 * has no DOM lib.
 */
const isWeb = Platform.OS === 'web';

const browser = globalThis as unknown as {
  alert?: (message: string) => void;
  confirm?: (message: string) => boolean;
};

function joinText(title: string, message?: string): string {
  return message ? `${title}\n\n${message}` : title;
}

/** Informational, nothing to decide. */
export function notify(title: string, message?: string): void {
  if (isWeb) {
    browser.alert?.(joinText(title, message));
    return;
  }
  Alert.alert(title, message);
}

/** Resolves true only on explicit confirmation; dismissing counts as cancel. */
export function confirmAction(
  title: string,
  message: string,
  options: { confirmLabel?: string; destructive?: boolean } = {}
): Promise<boolean> {
  const { confirmLabel = 'OK', destructive = false } = options;

  if (isWeb) {
    return Promise.resolve(browser.confirm?.(joinText(title, message)) ?? false);
  }

  return new Promise((resolve) => {
    Alert.alert(
      title,
      message,
      [
        { text: 'Cancel', style: 'cancel', onPress: () => resolve(false) },
        {
          text: confirmLabel,
          style: destructive ? 'destructive' : 'default',
          onPress: () => resolve(true),
        },
      ],
      { onDismiss: () => resolve(false) }
    );
  });
}
