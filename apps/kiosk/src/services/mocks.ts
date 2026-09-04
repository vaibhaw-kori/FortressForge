/**
 * Mock API for UI development when the backend is unavailable.
 *
 * NOT used in shipped builds. Toggle via `import.meta.env.VITE_USE_MOCKS`
 * or the helper `USE_MOCKS` below. When mock mode is on:
 *   - All API calls resolve locally with deterministic data.
 *   - The "generation" job walks through CREATED -> QUEUED -> PROCESSING ->
 *     GENERATING -> POST_PROCESSING -> ENCODING -> COMPLETED over a few
 *     seconds (configurable) so the UI screens can be exercised.
 *
 * To remove mocks from a build: set USE_MOCKS to false and delete this
 * file. The api.ts module is the only consumer.
 */
import type {
  ExperienceDTO,
  GenerationJobDTO,
  JobState,
  SessionDTO,
  SessionState,
} from '@aura/contracts';

const envFlag = (import.meta as ImportMeta & { env?: Record<string, string> }).env?.VITE_USE_MOCKS;
export const USE_MOCKS = envFlag === 'true' || envFlag === '1';

const nowIso = (): string => new Date().toISOString();
const randomId = (): string => Math.random().toString(36).slice(2, 18);

const SAMPLE_EXPERIENCES: ExperienceDTO[] = [
  {
    id: 'aurora',
    display_name: 'Aurora',
    description: 'Flowing neon ribbons drifting through an arctic sky.',
    duration_sec: 4.0,
    fps: 12,
    resolution: '720x1280',
    aspect_ratio: '9:16',
    thumbnail_url: null,
    enabled: true,
    display_order: 10,
    prompt: 'mock prompt',
    negative_prompt: null,
    visual_style: {
      aesthetic: 'cinematic',
      palette_name: 'aurora',
      keywords: ['aurora', 'neon', 'ethereal'],
      lighting: 'soft',
      texture: 'smooth',
    },
    motion: { strength: 0.7, camera_motion: 'dolly', easing: 'ease_in_out', intensity: 0.55, loop: false },
    model_params: {
      num_inference_steps: 28,
      guidance_scale: 7.5,
      motion_bucket_id: 180,
      seed_policy: 'random',
      fixed_seed: null,
      strength: 0.65,
      extra: {},
    },
    theme: { palette: { primary: '#7c5cff', accent: '#00d4ff', bg: '#050608' }, background_music: null },
    metadata: {},
    localized_names: null,
    localized_descriptions: null,
    supported_languages: ['en', 'ar'],
    default_language: 'en',
    rtl_text: true,
  },
  {
    id: 'mirage',
    display_name: 'Mirage',
    description: 'A shimmering desert oasis with golden particles.',
    duration_sec: 5.0,
    fps: 12,
    resolution: '720x1280',
    aspect_ratio: '9:16',
    thumbnail_url: null,
    enabled: true,
    display_order: 20,
    prompt: 'mock prompt',
    negative_prompt: null,
    visual_style: {
      aesthetic: 'environment',
      palette_name: 'mirage',
      keywords: ['desert', 'oasis', 'gold'],
      lighting: 'dramatic',
      texture: 'grain',
    },
    motion: { strength: 0.6, camera_motion: 'orbit', easing: 'ease_in_out', intensity: 0.5, loop: false },
    model_params: {
      num_inference_steps: 30,
      guidance_scale: 7.0,
      motion_bucket_id: 160,
      seed_policy: 'random',
      fixed_seed: null,
      strength: 0.6,
      extra: {},
    },
    theme: { palette: { primary: '#ffb547', accent: '#ffe7a3', bg: '#1a0f00' }, background_music: null },
    metadata: {},
    localized_names: null,
    localized_descriptions: null,
    supported_languages: ['en', 'ar'],
    default_language: 'en',
    rtl_text: true,
  },
  {
    id: 'pulse',
    display_name: 'Pulse',
    description: 'High-contrast geometric waves synced to a beat.',
    duration_sec: 3.0,
    fps: 24,
    resolution: '720x1280',
    aspect_ratio: '9:16',
    thumbnail_url: null,
    enabled: true,
    display_order: 30,
    prompt: 'mock prompt',
    negative_prompt: null,
    visual_style: {
      aesthetic: 'kinetic',
      palette_name: 'pulse',
      keywords: ['kinetic', 'geometric', 'beat'],
      lighting: 'high_key',
      texture: 'smooth',
    },
    motion: { strength: 0.85, camera_motion: 'parallax', easing: 'ease_out', intensity: 0.8, loop: true },
    model_params: {
      num_inference_steps: 22,
      guidance_scale: 8.0,
      motion_bucket_id: 220,
      seed_policy: 'random',
      fixed_seed: null,
      strength: 0.75,
      extra: {},
    },
    theme: { palette: { primary: '#ff3b8b', accent: '#ffffff', bg: '#0b0d12' }, background_music: null },
    metadata: {},
    localized_names: null,
    localized_descriptions: null,
    supported_languages: ['en', 'ar'],
    default_language: 'en',
    rtl_text: true,
  },
];

const sessions: Record<string, SessionDTO> = {};
const jobs: Record<string, GenerationJobDTO> = {};

function delay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

export const mockApi = {
  async listExperiences(_language: string): Promise<ExperienceDTO[]> {
    await delay(60);
    return SAMPLE_EXPERIENCES;
  },
  async getExperience(id: string, _language: string): Promise<ExperienceDTO> {
    await delay(40);
    const found = SAMPLE_EXPERIENCES.find((e) => e.id === id);
    if (!found) throw new Error('not_found');
    return found;
  },
  async createSession(language: string): Promise<SessionDTO> {
    await delay(60);
    const id = randomId();
    const s: SessionDTO = {
      id,
      language: language ?? null,
      theme_id: null,
      state: 'IDLE',
      capture_ref: null,
      created_at: nowIso(),
      updated_at: nowIso(),
    };
    sessions[id] = s;
    return s;
  },
  async transitionSession(
    sessionId: string,
    to: SessionState,
    extra: { language?: string; theme_id?: string },
  ): Promise<SessionDTO> {
    await delay(40);
    const s = sessions[sessionId];
    if (!s) throw new Error('not_found');
    const next: SessionDTO = {
      ...s,
      state: to,
      language: extra.language ?? s.language,
      theme_id: extra.theme_id ?? s.theme_id,
      updated_at: nowIso(),
    };
    sessions[sessionId] = next;
    return next;
  },
  async uploadCapture(sessionId: string, blob: Blob): Promise<{ key: string; size: number }> {
    await delay(300);
    const s = sessions[sessionId];
    if (!s) throw new Error('not_found');
    sessions[sessionId] = { ...s, state: 'UPLOADED', capture_ref: `captures/${sessionId}.jpg`, updated_at: nowIso() };
    return { key: `captures/${sessionId}.jpg`, size: blob.size };
  },
  async createJob(sessionId: string, experienceId: string): Promise<GenerationJobDTO> {
    await delay(80);
    const id = randomId();
    const job: GenerationJobDTO = {
      id,
      session_id: sessionId,
      experience_id: experienceId,
      provider_id: 'fake',
      state: 'CREATED',
      attempts: 0,
      max_attempts: 2,
      progress: 0,
      input_ref: `captures/${sessionId}.jpg`,
      output: null,
      error_code: null,
      error_message: null,
      provider_job_id: null,
      created_at: nowIso(),
      updated_at: nowIso(),
      started_at: null,
      finished_at: null,
    };
    jobs[id] = job;
    // Drive a fake progress arc in the background so UI can be tested.
    void this._progressJob(id);
    return job;
  },
  async getJob(jobId: string): Promise<GenerationJobDTO> {
    await delay(20);
    const j = jobs[jobId];
    if (!j) throw new Error('not_found');
    return j;
  },

  // Internal: fake job progression.
  async _progressJob(jobId: string): Promise<void> {
    const sequence: { state: JobState; pct: number; ms: number }[] = [
      { state: 'QUEUED', pct: 0.05, ms: 400 },
      { state: 'PROCESSING', pct: 0.15, ms: 600 },
      { state: 'GENERATING', pct: 0.55, ms: 1500 },
      { state: 'POST_PROCESSING', pct: 0.75, ms: 700 },
      { state: 'ENCODING', pct: 0.92, ms: 500 },
      { state: 'COMPLETED', pct: 1.0, ms: 200 },
    ];
    for (const step of sequence) {
      await delay(step.ms);
      const j = jobs[jobId];
      if (!j) return;
      jobs[jobId] = {
        ...j,
        state: step.state,
        progress: step.pct,
        updated_at: nowIso(),
        started_at: j.started_at ?? nowIso(),
        finished_at: step.state === 'COMPLETED' ? nowIso() : j.finished_at,
        output:
          step.state === 'COMPLETED'
            ? {
                key: `generated/${jobId}.mp4`,
                url: `https://cdn.mock/generated/${jobId}.mp4`,
                duration_sec: 4,
                codec: 'h264',
                size_bytes: null,
                width: 720,
                height: 1280,
                fps: 12,
                checksum_sha256: null,
              }
            : j.output,
      };
    }
  },
};