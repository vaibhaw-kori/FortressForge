/**
 * Typed API client for Display 1.
 *
 * Talks to the backend at API_PATHS base; the Vite dev server proxies
 * `/api/*` to the FastAPI service. Mock fallback lives in `./mocks.ts`
 * and is OFF unless the developer toggles `USE_MOCKS=true`.
 */
import {
  API_PATHS,
  ExperienceDTO,
  GenerationJobDTO,
  JobState,
  SessionDTO,
  SessionState,
} from '@aura/contracts';
import { USE_MOCKS, mockApi } from './mocks';

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      // ignore
    }
    const code =
      (body as { error?: { code?: string } } | null)?.error?.code ?? `http_${res.status}`;
    const message =
      (body as { error?: { message?: string } } | null)?.error?.message ?? res.statusText;
    const err = new ApiError(code, message, res.status);
    throw err;
  }
  return (await res.json()) as T;
}

export class ApiError extends Error {
  status: number;
  code: string;
  constructor(code: string, message: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

function kioskHeaders(): Record<string, string> {
  // In prod, inject via VITE_KIOSK_TOKEN (build-time). Never put RunPod secrets here.
  const token = (import.meta as unknown as { env?: Record<string, string> }).env?.VITE_KIOSK_TOKEN ?? 'kiosk-dev-token';
  return token ? { 'X-Kiosk-Token': token } : {};
}

export const api = {
  async listExperiences(language: string): Promise<ExperienceDTO[]> {
    if (USE_MOCKS) return mockApi.listExperiences(language);
    const res = await fetch(`${API_PATHS.experiences}?language=${encodeURIComponent(language)}`, {
      headers: { ...kioskHeaders() },
    });
    const body = await jsonOrThrow<{ items: ExperienceDTO[] }>(res);
    return body.items;
  },

  async getExperience(id: string, language: string): Promise<ExperienceDTO> {
    if (USE_MOCKS) return mockApi.getExperience(id, language);
    const res = await fetch(`${API_PATHS.experience(id)}?language=${encodeURIComponent(language)}`, {
      headers: { ...kioskHeaders() },
    });
    return jsonOrThrow<ExperienceDTO>(res);
  },

  async createSession(language: string): Promise<SessionDTO> {
    if (USE_MOCKS) return mockApi.createSession(language);
    const res = await fetch(API_PATHS.sessions, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...kioskHeaders() },
      body: JSON.stringify({ language }),
    });
    return jsonOrThrow<SessionDTO>(res);
  },

  async transitionSession(
    sessionId: string,
    to: SessionState,
    extra: { language?: string; theme_id?: string } = {},
  ): Promise<SessionDTO> {
    if (USE_MOCKS) return mockApi.transitionSession(sessionId, to, extra);
    const res = await fetch(API_PATHS.sessionTransition(sessionId), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...kioskHeaders() },
      body: JSON.stringify({ to, ...extra }),
    });
    return jsonOrThrow<SessionDTO>(res);
  },

  async uploadCapture(sessionId: string, blob: Blob): Promise<{ key: string; size: number }> {
    if (USE_MOCKS) return mockApi.uploadCapture(sessionId, blob);
    const fd = new FormData();
    fd.append('file', blob, 'capture.jpg');
    const res = await fetch(API_PATHS.capture(sessionId), {
      method: 'POST',
      headers: { ...kioskHeaders() },
      body: fd,
    });
    return jsonOrThrow<{ key: string; size: number }>(res);
  },

  async createJob(
    sessionId: string,
    experienceId: string,
  ): Promise<GenerationJobDTO> {
    if (USE_MOCKS) return mockApi.createJob(sessionId, experienceId);
    const res = await fetch(API_PATHS.jobs, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...kioskHeaders() },
      body: JSON.stringify({ session_id: sessionId, experience_id: experienceId }),
    });
    return jsonOrThrow<GenerationJobDTO>(res);
  },

  async getJob(jobId: string): Promise<GenerationJobDTO> {
    if (USE_MOCKS) return mockApi.getJob(jobId);
    const res = await fetch(API_PATHS.job(jobId), { headers: { ...kioskHeaders() } });
    return jsonOrThrow<GenerationJobDTO>(res);
  },
};

// Type-narrow the state machine: convenience exported type.
export type { JobState };