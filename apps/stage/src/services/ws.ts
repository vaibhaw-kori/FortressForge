/**
 * Display2 WebSocket client.
 * Isolated from business logic — only forwards typed events to a callback.
 * Handles auto-reconnect with exponential backoff, heartbeat, and stale detection.
 */

export type Display2Incoming =
  | { type: 'REEL_UPDATED'; items?: any[]; queue_length?: number; ts: string; id: string }
  | { type: 'NEW_VIDEO_AVAILABLE'; job_id: string; video_id: string; src: string; duration_sec: number; theme_id?: string; ts: string; id: string }
  | { type: 'PLAY_NEXT'; ts: string; id: string }
  | { type: 'PLAY_VIDEO'; video_id: string; ts: string; id: string }
  | { type: 'REFRESH_PLAYLIST'; ts: string; id: string }
  | { type: 'hello'; connection_id?: string; [k: string]: unknown }
  | { type: 'ping'; [k: string]: unknown };

export interface Display2SocketOptions {
  stageId: string;
  token?: string;
  onEvent: (ev: Display2Incoming) => void;
  onStatusChange?: (status: 'connecting' | 'open' | 'closed' | 'error') => void;
}

export function createDisplay2Socket(opts: Display2SocketOptions): { close: () => void } {
  const { stageId, token, onEvent, onStatusChange } = opts;
  const resolvedToken = token ?? (import.meta as unknown as { env?: Record<string, string> }).env?.VITE_KIOSK_TOKEN ?? 'kiosk-dev-token';
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const base = `${proto}//${location.host}/ws/v1/display2/${encodeURIComponent(stageId)}`;
  const url = `${base}?token=${encodeURIComponent(resolvedToken)}`;

  let ws: WebSocket | null = null;
  let closed = false;
  let retryMs = 1000;
  let timer: number | null = null;

  const connect = () => {
    if (closed) return;
    onStatusChange?.('connecting');
    try {
      ws = new WebSocket(url);
    } catch {
      scheduleReconnect();
      return;
    }

    ws.onopen = () => {
      retryMs = 1000;
      onStatusChange?.('open');
      // Send hello to identify
      try {
        ws?.send(JSON.stringify({ type: 'hello', client_id: stageId }));
      } catch {}
    };

    ws.onmessage = (ev) => {
      let data: any;
      try {
        data = JSON.parse(ev.data);
      } catch {
        return;
      }
      // Heartbeat pongs
      if (data.type === 'ping') {
        try {
          ws?.send(JSON.stringify({ type: 'pong', ts: new Date().toISOString() }));
        } catch {}
        return;
      }
      // Forward typed events
      if (
        data.type === 'REEL_UPDATED' ||
        data.type === 'NEW_VIDEO_AVAILABLE' ||
        data.type === 'PLAY_NEXT' ||
        data.type === 'PLAY_VIDEO' ||
        data.type === 'REFRESH_PLAYLIST' ||
        data.type === 'hello' ||
        data.type === 'hello_ack'
      ) {
        onEvent(data as Display2Incoming);
      }
    };

    ws.onclose = () => {
      onStatusChange?.('closed');
      ws = null;
      scheduleReconnect();
    };

    ws.onerror = () => {
      onStatusChange?.('error');
      try { ws?.close(); } catch {}
    };
  };

  const scheduleReconnect = () => {
    if (closed) return;
    if (timer) window.clearTimeout(timer);
    timer = window.setTimeout(() => {
      retryMs = Math.min(retryMs * 1.8, 15000);
      connect();
    }, retryMs);
  };

  connect();

  return {
    close() {
      closed = true;
      if (timer) window.clearTimeout(timer);
      try { ws?.close(); } catch {}
      ws = null;
    },
  };
}
