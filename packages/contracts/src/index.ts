/**
 * Shared AURA types.
 * Framework-free; mirrors the backend Pydantic schemas.
 */

// ---- API v1 ----

export const API_PATHS = {
  health: '/api/v1/health',
  ready: '/api/v1/ready',
  experiences: '/api/v1/experiences',
  experience: (id: string) => `/api/v1/experiences/${id}`,
  sessions: '/api/v1/sessions',
  session: (id: string) => `/api/v1/sessions/${id}`,
  sessionTransition: (id: string) => `/api/v1/sessions/${id}/transition`,
  capture: (sessionId: string) => `/api/v1/sessions/${sessionId}/capture`,
  jobs: '/api/v1/generation/jobs',
  job: (id: string) => `/api/v1/generation/jobs/${id}`,
  reelPlaylist: '/api/v1/reel/playlist',
  reelVideos: '/api/v1/reel/videos',
} as const;

export const WS_PATHS = {
  display1: (kioskId: string, token?: string) =>
    `/ws/v1/display1/${kioskId}${token ? `?token=${encodeURIComponent(token)}` : ''}`,
  display2: (stageId: string, token?: string) =>
    `/ws/v1/display2/${stageId}${token ? `?token=${encodeURIComponent(token)}` : ''}`,
  job: (jobId: string, token?: string) =>
    `/ws/v1/job/${jobId}${token ? `?token=${encodeURIComponent(token)}` : ''}`,
  operator: (token?: string) => `/ws/v1/operator${token ? `?token=${encodeURIComponent(token)}` : ''}`,
} as const;

// ---- Session ----

export type SessionState =
  | 'IDLE'
  | 'LANGUAGE_SELECTED'
  | 'THEME_SELECTED'
  | 'COUNTDOWN'
  | 'CAPTURING'
  | 'UPLOADED'
  | 'GENERATING'
  | 'COMPLETED'
  | 'ERROR';

export interface SessionDTO {
  id: string;
  language: string | null;
  theme_id: string | null;
  state: SessionState;
  capture_ref: string | null;
  created_at: string;
  updated_at: string;
}

// ---- Experience ----

export interface ExperienceThemeDTO {
  palette: Record<string, string>;
  background_music: string | null;
}

export interface MotionConfigDTO {
  strength: number;
  camera_motion: string;
  easing: string;
  intensity: number;
  loop: boolean;
}

export interface ModelParamsDTO {
  num_inference_steps: number;
  guidance_scale: number;
  motion_bucket_id: number;
  seed_policy: string;
  fixed_seed: number | null;
  strength: number;
  extra: Record<string, unknown>;
}

export interface VisualStyleDTO {
  aesthetic: string;
  palette_name: string;
  keywords: string[];
  lighting: string;
  texture: string;
}

export interface LocalizedTextDTO {
  language: string;
  value: string;
  fallback_language: string;
  rtl: boolean;
}

export interface ExperienceDTO {
  id: string;
  display_name: string;
  description: string;
  duration_sec: number;
  fps: number;
  resolution: string;
  aspect_ratio: string;
  thumbnail_url: string | null;
  enabled: boolean;
  display_order: number;
  prompt: string;
  negative_prompt: string | null;
  visual_style: VisualStyleDTO;
  motion: MotionConfigDTO;
  model_params: ModelParamsDTO;
  theme: ExperienceThemeDTO;
  metadata: Record<string, unknown>;
  localized_names: LocalizedTextDTO | null;
  localized_descriptions: LocalizedTextDTO | null;
  supported_languages: string[];
  default_language: string;
  rtl_text: boolean;
}

// ---- Generation job ----

export type JobState =
  | 'CREATED'
  | 'QUEUED'
  | 'PROCESSING'
  | 'GENERATING'
  | 'POST_PROCESSING'
  | 'ENCODING'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED'
  | 'TIMEOUT';

export interface VideoAssetDTO {
  key: string;
  url: string;
  duration_sec: number;
  codec: string;
  size_bytes: number | null;
  width: number | null;
  height: number | null;
  fps: number | null;
  checksum_sha256: string | null;
}

export interface GenerationJobDTO {
  id: string;
  session_id: string;
  experience_id: string;
  provider_id: string;
  state: JobState;
  attempts: number;
  max_attempts: number;
  progress: number;
  input_ref: string | null;
  output: VideoAssetDTO | null;
  error_code: string | null;
  error_message: string | null;
  provider_job_id: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
}

// ---- Reel ----

export type ReelItemKind = 'curated' | 'generated';

export interface ReelItemDTO {
  id: string;
  kind: ReelItemKind;
  src: string;
  title?: string | null;
  duration_sec: number;
  poster?: string | null;
  theme_id?: string | null;
}

// ---- Kiosk UI state machine (display-side, mirrors backend) ----

export type KioskScreen =
  | 'IDLE'
  | 'LANGUAGE_SELECTION'
  | 'EXPERIENCE_SELECTION'
  | 'READY_TO_CAPTURE'
  | 'COUNTDOWN'
  | 'CAPTURED'
  | 'UPLOADING'
  | 'GENERATING'
  | 'COMPLETED'
  | 'RESET'
  | 'ERROR';

export const KIOSK_SCREEN_TRANSITIONS: Record<KioskScreen, KioskScreen[]> = {
  IDLE: ['LANGUAGE_SELECTION'],
  LANGUAGE_SELECTION: ['EXPERIENCE_SELECTION'],
  EXPERIENCE_SELECTION: ['READY_TO_CAPTURE'],
  READY_TO_CAPTURE: ['COUNTDOWN', 'EXPERIENCE_SELECTION'],
  COUNTDOWN: ['CAPTURED', 'READY_TO_CAPTURE'],
  CAPTURED: ['UPLOADING', 'READY_TO_CAPTURE'],
  UPLOADING: ['GENERATING', 'ERROR', 'READY_TO_CAPTURE'],
  GENERATING: ['COMPLETED', 'ERROR'],
  COMPLETED: ['RESET'],
  RESET: ['IDLE', 'LANGUAGE_SELECTION'],
  ERROR: ['RESET', 'READY_TO_CAPTURE'],
};

// ---- WebSocket protocol ----

export type WSRole = 'display1' | 'display2' | 'operator';

export interface WSEnvelope<T extends string = string> {
  v: number;
  id: string;
  type: T;
  ts: string;
  role?: WSRole;
  [key: string]: unknown;
}

// Display1 events
export type Display1EventType =
  | 'GENERATION_STARTED'
  | 'GENERATION_PROGRESS'
  | 'GENERATION_COMPLETED'
  | 'GENERATION_FAILED';

export interface GenerationStartedEvent extends WSEnvelope<'GENERATION_STARTED'> {
  job_id: string;
  session_id: string;
  provider_id?: string;
  attempt?: number;
}
export interface GenerationProgressEvent extends WSEnvelope<'GENERATION_PROGRESS'> {
  job_id: string;
  progress: number;
  phase?: string | null;
  detail?: string | null;
}
export interface GenerationCompletedEvent extends WSEnvelope<'GENERATION_COMPLETED'> {
  job_id: string;
  output_ref: string;
  duration_sec?: number;
}
export interface GenerationFailedEvent extends WSEnvelope<'GENERATION_FAILED'> {
  job_id: string;
  code?: string;
  message?: string;
  transient?: boolean;
}

// Display2 events
export type Display2EventType =
  | 'REEL_UPDATED'
  | 'NEW_VIDEO_AVAILABLE'
  | 'PLAY_NEXT'
  | 'PLAY_VIDEO'
  | 'REFRESH_PLAYLIST';

export interface ReelUpdatedEvent extends WSEnvelope<'REEL_UPDATED'> {
  items?: ReelItemDTO[];
  queue_length?: number;
}
export interface NewVideoAvailableEvent extends WSEnvelope<'NEW_VIDEO_AVAILABLE'> {
  job_id: string;
  video_id: string;
  src: string;
  duration_sec: number;
  theme_id?: string;
}
export interface PlayNextEvent extends WSEnvelope<'PLAY_NEXT'> {}
export interface PlayVideoEvent extends WSEnvelope<'PLAY_VIDEO'> {
  video_id: string;
}
export interface RefreshPlaylistEvent extends WSEnvelope<'REFRESH_PLAYLIST'> {}

export type Display2Event =
  | ReelUpdatedEvent
  | NewVideoAvailableEvent
  | PlayNextEvent
  | PlayVideoEvent
  | RefreshPlaylistEvent;

export type WSEvent =
  | WSEnvelope<'hello'>
  | WSEnvelope<'hello_ack'>
  | WSEnvelope<'ping'>
  | WSEnvelope<'pong'>
  | WSEnvelope<'subscribed'>
  | WSEnvelope<'unsubscribed'>
  | WSEnvelope<'control_ack'>
  | WSEnvelope<'error'>
  | GenerationStartedEvent
  | GenerationProgressEvent
  | GenerationCompletedEvent
  | GenerationFailedEvent
  | Display2Event;
