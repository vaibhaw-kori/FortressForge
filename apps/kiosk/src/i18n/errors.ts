/**
 * Maps technical error codes (backend codes, HTTP codes, camera errors)
 * to guest-facing localized copy. The kiosk never shows raw codes,
 * HTTP statuses, or exception text to visitors.
 */
import type { KioskKey } from './catalog';

const CAMERA_PATTERNS = ['camera', 'capture', 'notallowed', 'notfound', 'devices', 'getusermedia'];
const NETWORK_PATTERNS = [
  'network',
  'http_',
  'fetch',
  'failed to fetch',
  'load failed',
  'timeout',
  'timeouterror',
  'abort',
  'offline',
];
const UPLOAD_PATTERNS = ['upload'];

function includesAny(haystack: string, needles: string[]): boolean {
  return needles.some((n) => haystack.includes(n));
}

/** Resolve a guest-facing i18n key for any technical error code/message. */
export function errorMessageKey(code?: string, message?: string): KioskKey {
  const hay = `${code ?? ''} ${message ?? ''}`.toLowerCase();
  if (includesAny(hay, CAMERA_PATTERNS)) return 'error.cameraDenied';
  if (includesAny(hay, UPLOAD_PATTERNS)) return 'error.uploadFailed';
  if (includesAny(hay, NETWORK_PATTERNS)) return 'error.network';
  return 'error.unknown';
}
