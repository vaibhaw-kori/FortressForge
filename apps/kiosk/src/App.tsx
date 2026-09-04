/**
 * Display 1 root.
 *
 * Owns the kiosk state machine and renders the active screen. No backend
 * logic here: all I/O goes through `services/api.ts`.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { BrandMark } from './components/BrandMark';
import { LanguagePill } from './components/LanguagePill';
import { ResetCountdown } from './components/ResetCountdown';
import { useDirection } from './hooks/useDirection';
import { useCountdown } from './hooks/useCountdown';
import { useJobProgress } from './hooks/useJobProgress';
import { useDisplay1Socket } from './hooks/useDisplay1Socket';
import { api, ApiError } from './services/api';
import { CapturedScreen } from './screens/CapturedScreen';
import { CompletedScreen } from './screens/CompletedScreen';
import { CountdownScreen } from './screens/CountdownScreen';
import { ErrorScreen } from './screens/ErrorScreen';
import { ExperienceScreen } from './screens/ExperienceScreen';
import { GeneratingScreen } from './screens/GeneratingScreen';
import { IdleScreen } from './screens/IdleScreen';
import { LanguageScreen } from './screens/LanguageScreen';
import { ReadyScreen } from './screens/ReadyScreen';
import { UploadingScreen } from './screens/UploadingScreen';
import { useKioskState } from './state/useKioskState';
import { useT } from './i18n/useT';
import './styles/globals.css';

const COUNTDOWN_SECONDS = 4;
const UPLOAD_FAKE_PROGRESS_MS = 1400;
const RESET_DELAY_SECONDS = 8;

export default function App() {
  const [state, dispatch] = useKioskState();
  useDirection(state.language);

  // Touch the catalog up-front so we can localize the language screen.
  const { t } = useT(state.language);

  // ---- Boot to LANGUAGE_SELECTION ----
  useEffect(() => {
    if (state.screen === 'IDLE') {
      dispatch({ type: 'BOOT_TO_LANGUAGE' });
    }
  }, [state.screen, dispatch]);

  // ---- Create + drive backend session ----
  const sessionRef = useRef<string | null>(null);
  const ensureSession = useCallback(
    async (language: string) => {
      try {
        if (!sessionRef.current) {
          const s = await api.createSession(language);
          sessionRef.current = s.id;
          dispatch({ type: 'SET_SESSION', session: s });
          await api.transitionSession(s.id, 'LANGUAGE_SELECTED', { language });
        }
        return sessionRef.current;
      } catch (err) {
        const e = err instanceof ApiError ? err : new ApiError('network', 'Network error', 0);
        dispatch({ type: 'ERROR', code: e.code, message: e.message });
        return null;
      }
    },
    [dispatch],
  );

  // ---- Language select ----
  const handleLanguage = useCallback(
    async (code: string) => {
      dispatch({ type: 'BUSY', busy: true });
      dispatch({ type: 'SELECT_LANGUAGE', language: code });
      const sid = await ensureSession(code);
      dispatch({ type: 'BUSY', busy: false });
      if (sid) {
        // Backed with LANGUAGE_SELECTED already; move to experience screen.
      }
    },
    [dispatch, ensureSession],
  );

  // ---- Experience select ----
  const handleExperience = useCallback(
    async (experienceId: string) => {
      if (!state.selectedExperience || state.selectedExperience.id !== experienceId) {
        // First click sets selection; second click advances.
        const exp = await api.getExperience(experienceId, state.language);
        dispatch({ type: 'SELECT_EXPERIENCE', experience: exp });
        return;
      }
      if (!sessionRef.current) return;
      try {
        dispatch({ type: 'BUSY', busy: true });
        await api.transitionSession(sessionRef.current, 'THEME_SELECTED', {
          theme_id: experienceId,
        });
        dispatch({ type: 'BUSY', busy: false });
        dispatch({ type: 'READY' });
      } catch (err) {
        dispatch({ type: 'ERROR', code: 'session_transition', message: 'session_transition' });
      }
    },
    [dispatch, state.language, state.selectedExperience],
  );

  // ---- Countdown ----
  useCountdown({
    total: COUNTDOWN_SECONDS,
    running: state.screen === 'COUNTDOWN',
    onTick: (remaining) => dispatch({ type: 'COUNTDOWN_TICK', remaining }),
    onComplete: async () => {
      try {
        const cap = await captureFromCamera();
        if (!cap) throw new Error('camera_unavailable');
        dispatch({ type: 'CAPTURED', blob: cap.blob, dataUrl: cap.dataUrl });
      } catch (err) {
        dispatch({ type: 'ERROR', code: 'capture_failed', message: 'capture_failed' });
      }
    },
  });

  // ---- Capture ----
  const captureFromCamera = useCallback(async (): Promise<{ blob: Blob; dataUrl: string } | null> => {
    // Find the active <video> element rendered by the screen.
    const v = document.querySelector<HTMLVideoElement>('video.capture-frame__video');
    if (!v || !v.videoWidth) return null;
    const w = v.videoWidth;
    const h = v.videoHeight;
    const canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    ctx.save();
    ctx.translate(w, 0);
    ctx.scale(-1, 1);
    ctx.drawImage(v, 0, 0, w, h);
    ctx.restore();
    const blob: Blob | null = await new Promise((r) =>
      canvas.toBlob((b) => r(b), 'image/jpeg', 0.92),
    );
    if (!blob) return null;
    return { blob, dataUrl: canvas.toDataURL('image/jpeg', 0.92) };
  }, []);

  // ---- Upload + generate ----
  const [uploadProgress, setUploadProgress] = useState(0);

  const handleContinueFromCaptured = useCallback(async () => {
    if (!state.captureBlob || !sessionRef.current || !state.selectedExperience) return;
    dispatch({ type: 'UPLOAD_START' });
    setUploadProgress(0);

    const startedAt = performance.now();
    const tick = () => {
      const elapsed = performance.now() - startedAt;
      const pct = Math.min(0.95, elapsed / UPLOAD_FAKE_PROGRESS_MS);
      setUploadProgress(pct);
    };
    const progressTimer = window.setInterval(tick, 80);

    try {
      await api.uploadCapture(sessionRef.current, state.captureBlob);
      // uploadCapture already marks session UPLOADED via captures endpoint; keep this idempotent
      try {
        await api.transitionSession(sessionRef.current, 'UPLOADED');
      } catch {
        // ignore if already UPLOADED
      }

      // Non-blocking: job creation returns immediately (201), worker processes async
      const job = await api.createJob(sessionRef.current, state.selectedExperience.id);
      window.clearInterval(progressTimer);
      setUploadProgress(1);
      dispatch({ type: 'GENERATE_START', job });
    } catch (err) {
      window.clearInterval(progressTimer);
      const e = err instanceof ApiError ? err : new ApiError('upload_failed', 'Upload failed', 0);
      dispatch({ type: 'ERROR', code: e.code, message: e.message });
    }
  }, [dispatch, state.captureBlob, state.selectedExperience]);

  // ---- Job progress: WebSocket (primary) + polling fallback ----
  useDisplay1Socket({
    jobId: state.job?.id ?? null,
    sessionId: state.session?.id ?? sessionRef.current,
    enabled: state.screen === 'GENERATING' || state.screen === 'UPLOADING',
    onEvent: (ev) => {
      if (ev.type === 'GENERATION_PROGRESS') {
        dispatch({ type: 'GENERATE_PROGRESS', progress: ev.progress });
      } else if (ev.type === 'GENERATION_STARTED') {
        dispatch({ type: 'GENERATE_PROGRESS', progress: 0.05 });
      } else if (ev.type === 'GENERATION_COMPLETED') {
        // Fetch full job to get output details
        if (state.job?.id) {
          api.getJob(state.job.id).then((job) => dispatch({ type: 'GENERATE_DONE', job })).catch(() => {
            // Fallback: dispatch with current job
            if (state.job) dispatch({ type: 'GENERATE_DONE', job: state.job });
          });
        }
      } else if (ev.type === 'GENERATION_FAILED') {
        dispatch({ type: 'ERROR', code: ev.code ?? 'job_failed', message: ev.message ?? 'Generation failed' });
      }
    },
  });

  useJobProgress({
    jobId: state.job?.id ?? null,
    onProgress: (job) => {
      // Only apply if not already completed via WS
      if (state.screen === 'GENERATING') {
        dispatch({ type: 'GENERATE_PROGRESS', progress: job.progress, state: job.state });
      }
    },
    onTerminal: (job) => {
      if (job.state === 'COMPLETED') dispatch({ type: 'GENERATE_DONE', job });
      else if (state.screen === 'GENERATING') dispatch({ type: 'ERROR', code: job.error_code ?? 'job_failed', message: job.error_message ?? 'Job failed' });
    },
  });

  // ---- Move to COMPLETED when generating reaches >=0.99 ----
  useEffect(() => {
    if (state.screen === 'GENERATING' && state.jobProgress >= 0.99 && state.job?.state === 'COMPLETED') {
      dispatch({ type: 'GENERATE_DONE', job: state.job });
    }
  }, [dispatch, state.screen, state.jobProgress, state.job]);

  // ---- Completed -> Reset ----
  useEffect(() => {
    if (state.screen === 'COMPLETED') {
      const id = window.setTimeout(() => dispatch({ type: 'RESET' }), 2500);
      return () => window.clearTimeout(id);
    }
  }, [state.screen, dispatch]);

  // ---- Helpers exposed to UI ----
  const resetAll = useCallback(() => {
    sessionRef.current = null;
    setUploadProgress(0);
    dispatch({ type: 'NEXT_VISITOR' });
  }, [dispatch]);

  const retry = useCallback(() => {
    if (state.captureBlob && state.selectedExperience) {
      dispatch({ type: 'GENERATE_PROGRESS', progress: 0 });
      handleContinueFromCaptured();
    } else {
      dispatch({ type: 'BACK_TO_EXPERIENCE' });
    }
  }, [dispatch, state.captureBlob, state.selectedExperience, handleContinueFromCaptured]);

  // ---- Rendering ----
  const screen = state.screen;
  const eyebrow = useMemo(() => state.selectedExperience?.display_name ?? '', [state.selectedExperience]);

  return (
    <main className={`stage ${state.direction === 'rtl' ? 'stage--rtl' : ''}`} data-lang={state.language}>
      <header className="stage__topbar">
        <BrandMark eyebrow={t('brand.eyebrow')} tagline={t('brand.tagline')} />
        <LanguagePill language={state.language} />
      </header>

      <section className="stage__main" aria-live="polite">
        {screen === 'IDLE' ? <IdleScreen onBegin={() => dispatch({ type: 'BOOT_TO_LANGUAGE' })} /> : null}
        {screen === 'LANGUAGE_SELECTION' ? (
          <LanguageScreen onSelect={handleLanguage} />
        ) : null}
        {screen === 'EXPERIENCE_SELECTION' ? (
          <ExperienceScreen
            language={state.language}
            selectedId={state.selectedExperience?.id ?? null}
            onSelect={(e) => handleExperience(e.id)}
            onBack={() => dispatch({ type: 'BACK_TO_LANGUAGE' })}
          />
        ) : null}
        {screen === 'READY_TO_CAPTURE' && state.selectedExperience ? (
          <ReadyScreen
            language={state.language}
            experience={state.selectedExperience}
            onCapture={() => dispatch({ type: 'COUNTDOWN_START', total: COUNTDOWN_SECONDS })}
            onChangeExperience={() => dispatch({ type: 'BACK_TO_EXPERIENCE' })}
          />
        ) : null}
        {screen === 'COUNTDOWN' ? (
          <CountdownScreen
            language={state.language}
            total={state.countdownTotal}
            remaining={state.countdownRemaining}
            onCancel={() => dispatch({ type: 'COUNTDOWN_CANCEL' })}
          />
        ) : null}
        {screen === 'CAPTURED' ? (
          <CapturedScreen
            language={state.language}
            dataUrl={state.captureDataUrl}
            onRetake={() => dispatch({ type: 'COUNTDOWN_START', total: COUNTDOWN_SECONDS })}
            onContinue={handleContinueFromCaptured}
          />
        ) : null}
        {screen === 'UPLOADING' ? (
          <UploadingScreen language={state.language} progress={uploadProgress} />
        ) : null}
        {screen === 'GENERATING' ? (
          <GeneratingScreen language={state.language} progress={state.jobProgress} state={state.job?.state ?? null} />
        ) : null}
        {screen === 'COMPLETED' ? (
          <CompletedScreen
            language={state.language}
            onNewVisitor={() => dispatch({ type: 'RESET' })}
          />
        ) : null}
        {screen === 'RESET' ? (
          <ResetCountdown
            seconds={RESET_DELAY_SECONDS}
            message={t('reset.title')}
            subtitle={t('reset.subtitle')}
            onDone={() => {
              sessionRef.current = null;
              dispatch({ type: 'NEXT_VISITOR' });
            }}
          />
        ) : null}
        {screen === 'ERROR' ? (
          <ErrorScreen
            language={state.language}
            code={state.error?.code}
            message={state.error?.message ?? t('error.unknown')}
            onRetry={retry}
            onReset={resetAll}
          />
        ) : null}
      </section>

      <footer className="stage__footer">
        <span className="muted">{eyebrow}</span>
        <span className="muted">AURA — Dubai</span>
      </footer>
    </main>
  );
}