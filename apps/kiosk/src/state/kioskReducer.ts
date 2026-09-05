/**
 * Centralized kiosk state (reducer) + actions.
 *
 * UI screens only dispatch actions; they never mutate state directly.
 * This is the single source of truth for the visitor flow.
 */
import type { ExperienceDTO, GenerationJobDTO, KioskScreen, SessionDTO } from '@aura/contracts';
import { assertTransition } from './kioskMachine';

export type Direction = 'ltr' | 'rtl';

export interface KioskState {
  screen: KioskScreen;
  language: string; // 'en' | 'ar' (kiosk-supported)
  direction: Direction;
  session: SessionDTO | null;
  selectedExperience: ExperienceDTO | null;
  captureBlob: Blob | null;
  captureDataUrl: string | null; // previewable frame
  job: GenerationJobDTO | null;
  jobProgress: number; // 0..1
  error: { code: string; message: string } | null;
  busy: boolean; // disables taps during async work
  countdownRemaining: number; // seconds left
  countdownTotal: number; // configured total
  cameraReady: boolean;
  cameraErrorMessage: string | null;
}

export const initialKioskState: KioskState = {
  screen: 'IDLE',
  language: 'en',
  direction: 'ltr',
  session: null,
  selectedExperience: null,
  captureBlob: null,
  captureDataUrl: null,
  job: null,
  jobProgress: 0,
  error: null,
  busy: false,
  countdownRemaining: 0,
  countdownTotal: 4,
  cameraReady: false,
  cameraErrorMessage: null,
};

export type KioskAction =
  | { type: 'BOOT_TO_LANGUAGE' }
  | { type: 'SELECT_LANGUAGE'; language: string }
  | { type: 'SELECT_EXPERIENCE'; experience: ExperienceDTO }
  | { type: 'BACK_TO_LANGUAGE' }
  | { type: 'BACK_TO_EXPERIENCE' }
  | { type: 'READY' }
  | { type: 'COUNTDOWN_START'; total: number }
  | { type: 'COUNTDOWN_TICK'; remaining: number }
  | { type: 'COUNTDOWN_CANCEL' }
  | { type: 'CAPTURED'; blob: Blob; dataUrl: string }
  | { type: 'UPLOAD_START' }
  | { type: 'UPLOAD_DONE' }
  | { type: 'GENERATE_START'; job: GenerationJobDTO }
  | { type: 'GENERATE_PROGRESS'; progress: number; state?: string }
  | { type: 'GENERATE_DONE'; job: GenerationJobDTO }
  | { type: 'ERROR'; code: string; message: string }
  | { type: 'RESET' }
  | { type: 'NEXT_VISITOR' }
  | { type: 'BUSY'; busy: boolean }
  | { type: 'SET_SESSION'; session: SessionDTO }
  | { type: 'CAMERA_READY' }
  | { type: 'CAMERA_ERROR'; message: string };

export function reducer(state: KioskState, action: KioskAction): KioskState {
  switch (action.type) {
    case 'BOOT_TO_LANGUAGE': {
      assertTransition(state.screen, 'LANGUAGE_SELECTION');
      return { ...state, screen: 'LANGUAGE_SELECTION' };
    }
    case 'SELECT_LANGUAGE': {
      const direction: Direction = action.language === 'ar' ? 'rtl' : 'ltr';
      assertTransition(state.screen, 'EXPERIENCE_SELECTION');
      return { ...state, screen: 'EXPERIENCE_SELECTION', language: action.language, direction };
    }
    case 'SELECT_EXPERIENCE': {
      assertTransition(state.screen, 'READY_TO_CAPTURE');
      return { ...state, screen: 'READY_TO_CAPTURE', selectedExperience: action.experience };
    }
    case 'BACK_TO_LANGUAGE': {
      return { ...state, screen: 'LANGUAGE_SELECTION' };
    }
    case 'BACK_TO_EXPERIENCE': {
      return { ...state, screen: 'EXPERIENCE_SELECTION', selectedExperience: null };
    }
    case 'READY': {
      return { ...state, screen: 'READY_TO_CAPTURE' };
    }
    case 'COUNTDOWN_START': {
      assertTransition(state.screen, 'COUNTDOWN');
      return {
        ...state,
        screen: 'COUNTDOWN',
        countdownTotal: action.total,
        countdownRemaining: action.total,
      };
    }
    case 'COUNTDOWN_TICK': {
      if (state.screen !== 'COUNTDOWN') return state;
      return { ...state, countdownRemaining: action.remaining };
    }
    case 'COUNTDOWN_CANCEL': {
      if (state.screen !== 'COUNTDOWN') return state;
      return { ...state, screen: 'READY_TO_CAPTURE', countdownRemaining: 0 };
    }
    case 'CAPTURED': {
      assertTransition(state.screen, 'CAPTURED');
      return {
        ...state,
        screen: 'CAPTURED',
        captureBlob: action.blob,
        captureDataUrl: action.dataUrl,
      };
    }
    case 'UPLOAD_START': {
      assertTransition(state.screen, 'UPLOADING');
      return { ...state, screen: 'UPLOADING' };
    }
    case 'UPLOAD_DONE': {
      // Transition to GENERATING happens after the job is created.
      return state;
    }
    case 'GENERATE_START': {
      assertTransition(state.screen, 'GENERATING');
      return { ...state, screen: 'GENERATING', job: action.job, jobProgress: 0 };
    }
    case 'GENERATE_PROGRESS': {
      if (state.screen !== 'GENERATING') return state;
      return { ...state, jobProgress: Math.max(state.jobProgress, action.progress) };
    }
    case 'GENERATE_DONE': {
      if (state.screen === 'COMPLETED') return state;
      assertTransition(state.screen, 'COMPLETED');
      return { ...state, screen: 'COMPLETED', job: action.job, jobProgress: 1 };
    }
    case 'ERROR': {
      return {
        ...state,
        screen: 'ERROR',
        error: { code: action.code, message: action.message },
      };
    }
    case 'RESET': {
      assertTransition(state.screen, 'RESET');
      return {
        ...state,
        screen: 'RESET',
        captureBlob: null,
        captureDataUrl: null,
        job: null,
        jobProgress: 0,
        error: null,
      };
    }
    case 'NEXT_VISITOR': {
      // From RESET or COMPLETED or ERROR, go to LANGUAGE_SELECTION for next visitor
      // Clear per-visitor state but keep language/direction
      return {
        ...state,
        screen: 'LANGUAGE_SELECTION',
        session: null,
        selectedExperience: null,
        captureBlob: null,
        captureDataUrl: null,
        job: null,
        jobProgress: 0,
        error: null,
        busy: false,
        countdownRemaining: 0,
      };
    }
    case 'BUSY': {
      return { ...state, busy: action.busy };
    }
    case 'SET_SESSION': {
      return { ...state, session: action.session };
    }
    case 'CAMERA_READY': {
      return { ...state, cameraReady: true, cameraErrorMessage: null };
    }
    case 'CAMERA_ERROR': {
      return { ...state, cameraReady: false, cameraErrorMessage: action.message };
    }
    default: {
      return state;
    }
  }
}