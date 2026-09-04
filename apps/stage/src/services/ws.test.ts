import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { createDisplay2Socket, Display2Incoming } from '../services/ws';

class MockWS {
  static instances: MockWS[] = [];
  url: string;
  sent: string[] = [];
  closed = false;
  onopen: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: ((ev: unknown) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockWS.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    if (this.closed) return;
    this.closed = true;
    this.onclose?.({});
  }
  /** test helpers */
  open() {
    this.onopen?.({});
  }
  message(data: unknown) {
    this.onmessage?.({ data: typeof data === 'string' ? data : JSON.stringify(data) });
  }
  fail() {
    this.onerror?.({});
  }
}

describe('Display2 socket', () => {
  beforeEach(() => {
    MockWS.instances = [];
    vi.useFakeTimers();
    vi.stubGlobal('WebSocket', MockWS as unknown as typeof WebSocket);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('connects with stage id + token in URL and sends hello on open', () => {
    const onEvent = vi.fn();
    const sock = createDisplay2Socket({ stageId: 'stage-1', token: 'tok', onEvent });
    expect(MockWS.instances.length).toBe(1);
    expect(MockWS.instances[0]!.url).toContain('/ws/v1/display2/stage-1');
    expect(MockWS.instances[0]!.url).toContain('token=tok');
    MockWS.instances[0]!.open();
    const hello = MockWS.instances[0]!.sent.map((s) => JSON.parse(s));
    expect(hello.some((m) => m.type === 'hello')).toBe(true);
    sock.close();
  });

  it('forwards NEW_VIDEO_AVAILABLE to onEvent', () => {
    const onEvent = vi.fn();
    const sock = createDisplay2Socket({ stageId: 's1', onEvent });
    MockWS.instances[0]!.open();
    onEvent.mockClear();
    MockWS.instances[0]!.message({
      type: 'NEW_VIDEO_AVAILABLE',
      job_id: 'j1',
      video_id: 'v1',
      src: '/generated/v1.mp4',
      duration_sec: 4,
      ts: new Date().toISOString(),
      id: 'e1',
    });
    expect(onEvent).toHaveBeenCalledTimes(1);
    expect((onEvent.mock.calls[0]![0] as Display2Incoming).type).toBe('NEW_VIDEO_AVAILABLE');
    sock.close();
  });

  it('answers ping with pong without forwarding', () => {
    const onEvent = vi.fn();
    const sock = createDisplay2Socket({ stageId: 's1', onEvent });
    MockWS.instances[0]!.open();
    onEvent.mockClear();
    MockWS.instances[0]!.sent.length = 0;
    MockWS.instances[0]!.message({ type: 'ping', ts: 'x' });
    expect(onEvent).not.toHaveBeenCalled();
    const sent = MockWS.instances[0]!.sent.map((s) => JSON.parse(s));
    expect(sent.some((m) => m.type === 'pong')).toBe(true);
    sock.close();
  });

  it('socket reconnect with backoff after close', () => {
    const onEvent = vi.fn();
    const onStatusChange = vi.fn();
    const sock = createDisplay2Socket({ stageId: 's1', onEvent, onStatusChange });
    expect(MockWS.instances.length).toBe(1);
    // First socket closes → schedule reconnect in 1000ms
    MockWS.instances[0]!.open();
    MockWS.instances[0]!.close();
    expect(MockWS.instances.length).toBe(1);
    vi.advanceTimersByTime(999);
    expect(MockWS.instances.length).toBe(1);
    vi.advanceTimersByTime(1);
    expect(MockWS.instances.length).toBe(2);
    // Second close → backoff grows (1000*1.8=1800)
    MockWS.instances[1]!.open();
    // open resets retryMs to 1000, so next delay is 1000 again.
    // To observe growth without an intervening open, close immediately:
    sock.close();
  });

  it('backoff grows when reconnects fail without open', () => {
    const onEvent = vi.fn();
    createDisplay2Socket({ stageId: 's1', onEvent });
    expect(MockWS.instances.length).toBe(1);
    // Close first socket before it ever opens (retryMs=1000)
    MockWS.instances[0]!.close();
    vi.advanceTimersByTime(1000);
    expect(MockWS.instances.length).toBe(2);
    // Close second without open: delay should now be 1800
    MockWS.instances[1]!.close();
    vi.advanceTimersByTime(1799);
    expect(MockWS.instances.length).toBe(2);
    vi.advanceTimersByTime(1);
    expect(MockWS.instances.length).toBe(3);
  });

  it('disconnect then reconnect resumes (new socket receives events)', () => {
    const onEvent = vi.fn();
    const sock = createDisplay2Socket({ stageId: 's1', onEvent });
    MockWS.instances[0]!.open();
    // Disconnect
    MockWS.instances[0]!.close();
    vi.advanceTimersByTime(1000);
    expect(MockWS.instances.length).toBe(2);
    // Reconnected socket opens and resumes
    MockWS.instances[1]!.open();
    const hello = MockWS.instances[1]!.sent.map((s) => JSON.parse(s));
    expect(hello.some((m) => m.type === 'hello')).toBe(true);
    onEvent.mockClear();
    MockWS.instances[1]!.message({ type: 'PLAY_NEXT', ts: new Date().toISOString(), id: 'e2' });
    expect(onEvent).toHaveBeenCalledTimes(1);
    expect((onEvent.mock.calls[0]![0] as Display2Incoming).type).toBe('PLAY_NEXT');
    sock.close();
  });

  it('close() stops further reconnects', () => {
    const onEvent = vi.fn();
    const sock = createDisplay2Socket({ stageId: 's1', onEvent });
    MockWS.instances[0]!.open();
    sock.close();
    // Even if the socket later closes, no reconnect should be scheduled
    MockWS.instances[0]!.close();
    vi.advanceTimersByTime(20000);
    expect(MockWS.instances.length).toBe(1);
  });

  it('malformed JSON is ignored', () => {
    const onEvent = vi.fn();
    const sock = createDisplay2Socket({ stageId: 's1', onEvent });
    MockWS.instances[0]!.open();
    onEvent.mockClear();
    MockWS.instances[0]!.onmessage?.({ data: 'not-json{{{' });
    expect(onEvent).not.toHaveBeenCalled();
    sock.close();
  });
});
