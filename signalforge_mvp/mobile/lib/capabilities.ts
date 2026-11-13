import { Platform } from 'react-native';

/**
 * What each platform is allowed to do.
 *
 * Mobile is read + triage: see your issues, resolve or ignore them, sign out.
 * Anything that creates or changes account state — signing up, making projects,
 * minting API keys, changing plan — is desk work and lives on the web
 * dashboard. Nobody pastes a 40-character key into a server from a phone.
 *
 * Triage deliberately stays on both. A push notification you can't act on is a
 * dead end: you get woken up and can do nothing until you reach a laptop.
 *
 * This is one file on purpose. The same codebase builds web and native, so a
 * scattered `Platform.OS === 'web'` check is how the web dashboard quietly
 * loses a button. Screens import from here; nothing else decides.
 */
const isWeb = Platform.OS === 'web';

export const canSignUp = isWeb;
export const canCreateProjects = isWeb;
export const canManageApiKeys = isWeb;
export const canChangePlan = isWeb;
/** Irreversible and takes the whole account with it — keep it off a phone. */
export const canDeleteAccount = isWeb;

/** Shown on mobile wherever an action was withheld. */
export const WEB_ONLY_HINT = 'Sign in to the web dashboard to do this.';
