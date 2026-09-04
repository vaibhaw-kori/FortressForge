import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { api, ApiError } from './api';

function jsonResponse(body: unknown, status = 200, statusText = 'OK') {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText,
    json: async () => body,
  } as Response;
}

describe('kiosk api client', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('upload success returns key+size', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ key: 'captures/s1.jpg', size: 1234 })));
    const out = await api.uploadCapture('s1', new Blob(['x'], { type: 'image/jpeg' }));
    expect(out).toEqual({ key: 'captures/s1.jpg', size: 1234 });
  });

  it('upload failure (500) throws ApiError with status 500', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({ error: { code: 'upload_failed', message: 'boom' } }, 500, 'Internal Server Error'),
      ),
    );
    try {
      await api.uploadCapture('s1', new Blob(['x']));
      expect.unreachable('should have thrown');
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      const err = e as ApiError;
      expect(err.status).toBe(500);
      expect(err.code).toBe('upload_failed');
    }
  });

  it('invalid capture (422 validation_failed) surfaces code', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({ error: { code: 'validation_failed', message: 'bad image' } }, 422, 'Unprocessable Entity'),
      ),
    );
    try {
      await api.uploadCapture('s1', new Blob(['x']));
      expect.unreachable('should have thrown');
    } catch (e) {
      const err = e as ApiError;
      expect(err.code).toBe('validation_failed');
      expect(err.status).toBe(422);
    }
  });

  it('network error throws ApiError with code network_error and status 0', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    try {
      await api.uploadCapture('s1', new Blob(['x']));
      expect.unreachable('should have thrown');
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      const err = e as ApiError;
      expect(err.code).toBe('network_error');
      expect(err.status).toBe(0);
    }
  });

  it('createSession success', async () => {
    const session = { id: 's1', language: 'en', theme_id: null, state: 'IDLE' };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(session)));
    const out = await api.createSession('en');
    expect(out.id).toBe('s1');
  });

  it('createJob success', async () => {
    const job = { id: 'j1', state: 'QUEUED', progress: 0 };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(job)));
    const out = await api.createJob('s1', 'aurora');
    expect(out.id).toBe('j1');
  });

  it('getJob failure (404) throws ApiError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ error: { code: 'not_found', message: 'no job' } }, 404, 'Not Found')),
    );
    try {
      await api.getJob('missing');
      expect.unreachable('should have thrown');
    } catch (e) {
      const err = e as ApiError;
      expect(err.status).toBe(404);
      expect(err.code).toBe('not_found');
    }
  });

  it('non-JSON error body falls back to http_<status> code', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        statusText: 'Service Unavailable',
        json: async () => {
          throw new Error('no json');
        },
      } as unknown as Response),
    );
    try {
      await api.getJob('j1');
      expect.unreachable('should have thrown');
    } catch (e) {
      const err = e as ApiError;
      expect(err.status).toBe(503);
      expect(err.code).toBe('http_503');
    }
  });
});
