/**
 * Poll a generation job until terminal. Emits progress updates.
 * Intentionally does NOT open a WS — the WS gateway is wired separately
 * by the backend later; this hook is the safe fallback that works
 * without any socket.
 */
import { useEffect, useRef } from 'react';
import type { GenerationJobDTO } from '@aura/contracts';
import { api } from '../services/api';

const TERMINAL: ReadonlyArray<GenerationJobDTO['state']> = [
  'COMPLETED',
  'FAILED',
  'CANCELLED',
  'TIMEOUT',
];

export interface UseJobProgressOptions {
  jobId: string | null;
  onProgress: (job: GenerationJobDTO) => void;
  onTerminal: (job: GenerationJobDTO) => void;
  intervalMs?: number;
}

export function useJobProgress({
  jobId,
  onProgress,
  onTerminal,
  intervalMs = 500,
}: UseJobProgressOptions): void {
  const onProgressRef = useRef(onProgress);
  const onTerminalRef = useRef(onTerminal);
  onProgressRef.current = onProgress;
  onTerminalRef.current = onTerminal;

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const job = await api.getJob(jobId);
        if (cancelled) return;
        onProgressRef.current(job);
        if (TERMINAL.includes(job.state)) {
          onTerminalRef.current(job);
          return true;
        }
        return false;
      } catch {
        return false;
      }
    };
    let stopped = false;
    void (async () => {
      while (!stopped && !cancelled) {
        const done = await tick();
        if (done || cancelled) break;
        await new Promise((r) => setTimeout(r, intervalMs));
      }
    })();
    return () => {
      cancelled = true;
      stopped = true;
    };
  }, [jobId, intervalMs]);
}