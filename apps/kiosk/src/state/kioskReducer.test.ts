import { describe, expect, it } from 'vitest';
import { initialKioskState, KioskState, reducer } from '../state/kioskReducer';

function step(state: KioskState, action: Parameters<typeof reducer>[1]): KioskState {
  return reducer(state, action);
}

describe('kiosk FSM', () => {
  it('boots into LANGUAGE_SELECTION from IDLE', () => {
    const next = step(initialKioskState, { type: 'BOOT_TO_LANGUAGE' });
    expect(next.screen).toBe('LANGUAGE_SELECTION');
  });

  it('selecting English advances to EXPERIENCE_SELECTION', () => {
    let s = step(initialKioskState, { type: 'BOOT_TO_LANGUAGE' });
    s = step(s, { type: 'SELECT_LANGUAGE', language: 'en' });
    expect(s.screen).toBe('EXPERIENCE_SELECTION');
    expect(s.direction).toBe('ltr');
  });

  it('selecting Arabic sets RTL direction', () => {
    let s = step(initialKioskState, { type: 'BOOT_TO_LANGUAGE' });
    s = step(s, { type: 'SELECT_LANGUAGE', language: 'ar' });
    expect(s.direction).toBe('rtl');
  });

  it('experience selection moves to READY_TO_CAPTURE', () => {
    let s = step(initialKioskState, { type: 'BOOT_TO_LANGUAGE' });
    s = step(s, { type: 'SELECT_LANGUAGE', language: 'en' });
    s = step(s, {
      type: 'SELECT_EXPERIENCE',
      experience: {
        id: 'aurora',
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
      },
    });
    expect(s.screen).toBe('READY_TO_CAPTURE');
  });

  it('countdown flow: READY -> COUNTDOWN -> CAPTURED -> UPLOADING -> GENERATING -> COMPLETED -> RESET', () => {
    let s = step(initialKioskState, { type: 'BOOT_TO_LANGUAGE' });
    s = step(s, { type: 'SELECT_LANGUAGE', language: 'en' });
    s = step(s, {
      type: 'SELECT_EXPERIENCE',
      experience: {
        id: 'aurora',
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
      },
    });

    s = step(s, { type: 'COUNTDOWN_START', total: 3 });
    expect(s.screen).toBe('COUNTDOWN');
    expect(s.countdownRemaining).toBe(3);

    s = step(s, { type: 'COUNTDOWN_TICK', remaining: 2 });
    expect(s.countdownRemaining).toBe(2);

    s = step(s, {
      type: 'CAPTURED',
      blob: new Blob(['x'], { type: 'image/jpeg' }),
      dataUrl: 'data:image/jpeg;base64,',
    });
    expect(s.screen).toBe('CAPTURED');
    expect(s.captureBlob).not.toBeNull();

    s = step(s, { type: 'UPLOAD_START' });
    expect(s.screen).toBe('UPLOADING');

    s = step(s, {
      type: 'GENERATE_START',
      job: {
        id: 'j1',
        session_id: 's1',
        experience_id: 'aurora',
        provider_id: 'fake',
        state: 'QUEUED',
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
      },
    });
    expect(s.screen).toBe('GENERATING');

    s = step(s, { type: 'GENERATE_PROGRESS', progress: 0.6 });
    expect(s.jobProgress).toBe(0.6);

    s = step(s, {
      type: 'GENERATE_DONE',
      job: {
        id: 'j1',
        session_id: 's1',
        experience_id: 'aurora',
        provider_id: 'fake',
        state: 'COMPLETED',
        attempts: 0,
        max_attempts: 1,
        progress: 1,
        input_ref: null,
        output: null,
        error_code: null,
        error_message: null,
        provider_job_id: null,
        created_at: '',
        updated_at: '',
        started_at: null,
        finished_at: '',
      },
    });
    expect(s.screen).toBe('COMPLETED');
    expect(s.jobProgress).toBe(1);

    s = step(s, { type: 'RESET' });
    expect(s.screen).toBe('RESET');
  });

  it('illegal transition throws', () => {
    expect(() =>
      step(initialKioskState, { type: 'GENERATE_START', job: {} as any }),
    ).toThrow();
  });
});