import { describe, expect, it } from 'vitest';
import { initialKioskState, KioskState, reducer } from './kioskReducer';
import type { ExperienceDTO, GenerationJobDTO } from '@aura/contracts';

function step(state: KioskState, action: Parameters<typeof reducer>[1]): KioskState {
  return reducer(state, action);
}

function fakeExperience(id = 'aurora'): ExperienceDTO {
  return {
    id,
    display_name: 'Aurora',
    description: 'd',
    duration_sec: 4,
    fps: 12,
    resolution: '720x1280',
    aspect_ratio: '9:16',
    thumbnail_url: null,
    enabled: true,
    display_order: 10,
    prompt: 'p',
    negative_prompt: null,
    visual_style: {
      aesthetic: 'cinematic',
      palette_name: 'aurora',
      keywords: [],
      lighting: 'soft',
      texture: 'smooth',
    },
    motion: { strength: 0.7, camera_motion: 'dolly', easing: 'ease_in_out', intensity: 0.5, loop: false },
    model_params: {
      num_inference_steps: 25,
      guidance_scale: 7,
      motion_bucket_id: 127,
      seed_policy: 'random',
      fixed_seed: null,
      strength: 0.7,
      extra: {},
    },
    theme: { palette: {}, background_music: null },
    metadata: {},
    localized_names: null,
    localized_descriptions: null,
    supported_languages: ['en', 'ar'],
    default_language: 'en',
    rtl_text: true,
  };
}

function fakeJob(state: GenerationJobDTO['state'] = 'QUEUED', id = 'j1'): GenerationJobDTO {
  return {
    id,
    session_id: 's1',
    experience_id: 'aurora',
    provider_id: 'fake',
    state,
    attempts: 0,
    max_attempts: 1,
    progress: 0,
    input_ref: null,
    output: null,
    error_code: null,
    error_message: null,
    provider_job_id: null,
    created_at: '',
    updated_at: '',
    started_at: null,
    finished_at: null,
  };
}

function happyPathToGenerating(expId = 'aurora', jobId = 'j1'): KioskState {
  let s = step(initialKioskState, { type: 'BOOT_TO_LANGUAGE' });
  s = step(s, { type: 'SELECT_LANGUAGE', language: 'en' });
  s = step(s, { type: 'SELECT_EXPERIENCE', experience: fakeExperience(expId) });
  s = step(s, { type: 'COUNTDOWN_START', total: 3 });
  s = step(s, { type: 'CAPTURED', blob: new Blob(['x'], { type: 'image/jpeg' }), dataUrl: 'data:,' });
  s = step(s, { type: 'UPLOAD_START' });
  s = step(s, { type: 'GENERATE_START', job: fakeJob('QUEUED', jobId) });
  return s;
}

describe('kiosk failure recovery', () => {
  it('ERROR → retry (BACK_TO_EXPERIENCE) → READY recovers to READY_TO_CAPTURE', () => {
    let s = happyPathToGenerating();
    // Simulate upload/generate failure surfaced as ERROR
    s = step(s, { type: 'ERROR', code: 'upload_failed', message: 'boom' });
    expect(s.screen).toBe('ERROR');
    expect(s.error?.code).toBe('upload_failed');

    // RETRY path used by App.retry(): back to experience selection when
    // there is no usable capture, then re-select and READY.
    s = step(s, { type: 'BACK_TO_EXPERIENCE' });
    expect(s.screen).toBe('EXPERIENCE_SELECTION');
    s = step(s, { type: 'SELECT_EXPERIENCE', experience: fakeExperience() });
    expect(s.screen).toBe('READY_TO_CAPTURE');
    s = step(s, { type: 'READY' });
    expect(s.screen).toBe('READY_TO_CAPTURE');
  });

  it('ERROR → RESET → NEXT_VISITOR starts a new session without reload', () => {
    let s = happyPathToGenerating();
    s = step(s, { type: 'ERROR', code: 'job_failed', message: 'gpu exploded' });
    expect(s.screen).toBe('ERROR');

    s = step(s, { type: 'RESET' });
    expect(s.screen).toBe('RESET');
    expect(s.captureBlob).toBeNull();
    expect(s.job).toBeNull();
    expect(s.error).toBeNull();

    s = step(s, { type: 'NEXT_VISITOR' });
    expect(s.screen).toBe('LANGUAGE_SELECTION');
    // New session: language flow works again
    s = step(s, { type: 'SELECT_LANGUAGE', language: 'ar' });
    expect(s.screen).toBe('EXPERIENCE_SELECTION');
    expect(s.language).toBe('ar');
    expect(s.session).toBeNull();
  });

  it('GENERATE failure (GENERATING → ERROR) → RESET → new session', () => {
    let s = happyPathToGenerating();
    expect(s.screen).toBe('GENERATING');
    // GENERATION_FAILED websocket event maps to ERROR (see App.tsx)
    s = step(s, { type: 'ERROR', code: 'GENERATION_FAILED', message: 'Generation failed' });
    expect(s.screen).toBe('ERROR');
    expect(s.error?.code).toBe('GENERATION_FAILED');

    s = step(s, { type: 'RESET' });
    expect(s.screen).toBe('RESET');
    s = step(s, { type: 'NEXT_VISITOR' });
    expect(s.screen).toBe('LANGUAGE_SELECTION');

    // Fresh happy path without page reload
    s = step(s, { type: 'SELECT_LANGUAGE', language: 'en' });
    s = step(s, { type: 'SELECT_EXPERIENCE', experience: fakeExperience() });
    expect(s.screen).toBe('READY_TO_CAPTURE');
  });

  it('repeated sessions: happy-path reducer flow 3x sequentially', () => {
    let s: KioskState = initialKioskState;
    // Deterministic 3x loop: full happy path → RESET → NEXT_VISITOR each time.
    for (let i = 0; i < 3; i++) {
      let t = step(initialKioskState, { type: 'BOOT_TO_LANGUAGE' });
      t = step(t, { type: 'SELECT_LANGUAGE', language: 'en' });
      t = step(t, { type: 'SELECT_EXPERIENCE', experience: fakeExperience() });
      t = step(t, { type: 'COUNTDOWN_START', total: 3 });
      t = step(t, {
        type: 'CAPTURED',
        blob: new Blob([`frame-${i}`], { type: 'image/jpeg' }),
        dataUrl: `data:,${i}`,
      });
      t = step(t, { type: 'UPLOAD_START' });
      t = step(t, { type: 'GENERATE_START', job: fakeJob('QUEUED', `job-${i}`) });
      t = step(t, { type: 'GENERATE_PROGRESS', progress: 0.5 });
      t = step(t, { type: 'GENERATE_DONE', job: fakeJob('COMPLETED', `job-${i}`) });
      expect(t.screen).toBe('COMPLETED');
      t = step(t, { type: 'RESET' });
      expect(t.screen).toBe('RESET');
      t = step(t, { type: 'NEXT_VISITOR' });
      expect(t.screen).toBe('LANGUAGE_SELECTION');
      expect(t.captureBlob).toBeNull();
      expect(t.job).toBeNull();
      s = t;
    }
    expect(s.screen).toBe('LANGUAGE_SELECTION');
  });

  it('ERROR preserves ability to complete a later session', () => {
    let s = happyPathToGenerating();
    s = step(s, { type: 'ERROR', code: 'transient', message: 'blip' });
    s = step(s, { type: 'RESET' });
    s = step(s, { type: 'NEXT_VISITOR' });
    s = step(s, { type: 'SELECT_LANGUAGE', language: 'en' });
    s = step(s, { type: 'SELECT_EXPERIENCE', experience: fakeExperience() });
    s = step(s, { type: 'COUNTDOWN_START', total: 2 });
    s = step(s, {
      type: 'CAPTURED',
      blob: new Blob(['y'], { type: 'image/jpeg' }),
      dataUrl: 'data:,y',
    });
    s = step(s, { type: 'UPLOAD_START' });
    s = step(s, { type: 'GENERATE_START', job: fakeJob() });
    s = step(s, { type: 'GENERATE_DONE', job: fakeJob('COMPLETED') });
    expect(s.screen).toBe('COMPLETED');
    expect(s.error).toBeNull();
  });
});
