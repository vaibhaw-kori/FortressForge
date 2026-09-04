import { describe, expect, it } from 'vitest';
import { errorMessageKey } from './errors';

describe('errorMessageKey (guest-facing copy mapping)', () => {
  it('maps camera/capture codes to cameraDenied', () => {
    expect(errorMessageKey('capture_failed')).toBe('error.cameraDenied');
    expect(errorMessageKey('camera_unavailable')).toBe('error.cameraDenied');
    expect(errorMessageKey('NotAllowedError', 'permission denied')).toBe('error.cameraDenied');
  });

  it('maps upload codes to uploadFailed', () => {
    expect(errorMessageKey('upload_failed')).toBe('error.uploadFailed');
  });

  it('maps network/http codes to network', () => {
    expect(errorMessageKey('network_error')).toBe('error.network');
    expect(errorMessageKey('http_500', 'Internal Server Error')).toBe('error.network');
    expect(errorMessageKey(undefined, 'Failed to fetch')).toBe('error.network');
  });

  it('falls back to unknown for backend job codes', () => {
    expect(errorMessageKey('job_failed', 'Generation failed')).toBe('error.unknown');
    expect(errorMessageKey('session_transition', 'x')).toBe('error.unknown');
    expect(errorMessageKey(undefined, undefined)).toBe('error.unknown');
  });
});
