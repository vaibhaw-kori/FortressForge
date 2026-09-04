import { useEffect, useRef } from 'react';

export type Display1Event =
  | { type: 'GENERATION_STARTED'; job_id: string; session_id?: string; provider_id?: string }
  | { type: 'GENERATION_PROGRESS'; job_id: string; progress: number; phase?: string }
  | { type: 'GENERATION_COMPLETED'; job_id: string; output_ref: string; duration_sec?: number }
  | { type: 'GENERATION_FAILED'; job_id: string; code?: string; message?: string };

interface Options {
  sessionId?: string | null;
  jobId?: string | null;
  kioskId?: string;
  enabled?: boolean;
  onEvent: (ev: Display1Event) => void;
}

export function useDisplay1Socket({ sessionId, jobId, kioskId = 'kiosk-1', enabled = true, onEvent }: Options) {
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    if (!enabled) return;
    if (!jobId && !sessionId) return;

    const token = (import.meta as unknown as { env?: Record<string, string> }).env?.VITE_KIOSK_TOKEN ?? 'kiosk-dev-token';
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    // Prefer per-job channel for precise delivery, fallback to display1 channel
    const base = jobId
      ? `${proto}//${location.host}/ws/v1/job/${encodeURIComponent(jobId)}?token=${encodeURIComponent(token)}`
      : `${proto}//${location.host}/ws/v1/display1/${encodeURIComponent(kioskId)}?token=${encodeURIComponent(token)}`;

    let ws: WebSocket | null = null;
    let closed = false;
    let retryMs = 1000;
    let timer: number | null = null;

    const connect = () => {
      if (closed) return;
      try {
        ws = new WebSocket(base);
      } catch {
        schedule();
        return;
      }
      ws.onopen = () => {
        retryMs = 1000;
        // Subscribe to job if using display1 channel
        if (!jobId && sessionId) {
          try { ws?.send(JSON.stringify({ type: 'subscribe', job_id: sessionId })); } catch {}
        }
        if (jobId) {
          try { ws?.send(JSON.stringify({ type: 'subscribe', job_id: jobId })); } catch {}
        }
      };
      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data);
          if (data.type === 'ping') {
            try { ws?.send(JSON.stringify({ type: 'pong' })); } catch {}
            return;
          }
          if (
            data.type === 'GENERATION_STARTED' ||
            data.type === 'GENERATION_PROGRESS' ||
            data.type === 'GENERATION_COMPLETED' ||
            data.type === 'GENERATION_FAILED'
          ) {
            // Filter by jobId if specified
            if (jobId && data.job_id !== jobId) return;
            onEventRef.current(data as Display1Event);
          }
        } catch {}
      };
      ws.onclose = () => {
        if (!closed) schedule();
      };
      ws.onerror = () => {
        try { ws?.close(); } catch {}
      };
    };

    const schedule = () => {
      if (closed) return;
      if (timer) window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        retryMs = Math.min(retryMs * 1.6, 10000);
        connect();
      }, retryMs);
    };

    connect();
    return () => {
      closed = true;
      if (timer) window.clearTimeout(timer);
      try { ws?.close(); } catch {}
    };
  }, [jobId, sessionId, kioskId, enabled]);
}
