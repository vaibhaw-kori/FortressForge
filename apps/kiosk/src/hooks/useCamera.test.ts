import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { useCamera } from './useCamera';

function mockStream() {
  const stop = vi.fn();
  const track = { stop, kind: 'video' };
  return {
    stop,
    stream: { getTracks: () => [track] } as unknown as MediaStream,
    track,
  };
}

describe('useCamera', () => {
  const realMediaDevices = () => (navigator as unknown as { mediaDevices?: unknown }).mediaDevices;

  let savedMediaDevices: unknown;

  beforeEach(() => {
    savedMediaDevices = (navigator as unknown as { mediaDevices?: unknown }).mediaDevices;
    vi.restoreAllMocks();
  });

  afterEach(() => {
    Object.defineProperty(navigator, 'mediaDevices', {
      value: savedMediaDevices,
      configurable: true,
      writable: true,
    });
    vi.restoreAllMocks();
    vi.unstubAllGlobals?.();
  });

  it('success → ready true, capture returns blob+dataUrl', async () => {
    const { stream } = mockStream();
    const getUserMedia = vi.fn().mockResolvedValue(stream);
    Object.defineProperty(navigator, 'mediaDevices', {
      value: { getUserMedia },
      configurable: true,
      writable: true,
    });

    // Mock canvas pipeline
    const fakeBlob = new Blob(['jpeg-bytes'], { type: 'image/jpeg' });
    const drawImage = vi.fn();
    const ctx = { save: vi.fn(), translate: vi.fn(), scale: vi.fn(), drawImage, restore: vi.fn() };
    const origCreateElement = document.createElement.bind(document);
    const createSpy = vi.spyOn(document, 'createElement').mockImplementation(((tag: string, ...rest: unknown[]) => {
      if (tag === 'canvas') {
        return {
          width: 0,
          height: 0,
          getContext: () => ctx,
          toBlob: (cb: (b: Blob | null) => void) => cb(fakeBlob),
          toDataURL: () => 'data:image/jpeg;base64,AAA',
        } as unknown as HTMLCanvasElement;
      }
      return origCreateElement(tag as never, ...(rest as never[])) as unknown as HTMLElement;
    }) as typeof document.createElement);

    const { result } = renderHook(() => useCamera());

    await waitFor(() => expect(result.current.ready).toBe(true));
    expect(result.current.errorMessage).toBeNull();
    expect(getUserMedia).toHaveBeenCalledTimes(1);

    // Attach a fake video element for capture
    const video = document.createElement('video');
    Object.defineProperties(video, {
      videoWidth: { value: 1280, configurable: true },
      videoHeight: { value: 720, configurable: true },
    });
    await act(async () => {
      (result.current.videoRef as unknown as { current: unknown }).current = video;
    });

    let out: { blob: Blob; dataUrl: string } | null = null;
    await act(async () => {
      out = await result.current.capture();
    });
    expect(out).not.toBeNull();
    expect(out!.blob).toBe(fakeBlob);
    expect(out!.dataUrl).toBe('data:image/jpeg;base64,AAA');
    expect(drawImage).toHaveBeenCalled();
    createSpy.mockRestore();
  });

  it('camera unavailable (no navigator.mediaDevices) → "Camera API not available"', async () => {
    Object.defineProperty(navigator, 'mediaDevices', {
      value: undefined,
      configurable: true,
      writable: true,
    });
    const { result } = renderHook(() => useCamera());
    await waitFor(() => expect(result.current.errorMessage).toBe('Camera API not available'));
    expect(result.current.ready).toBe(false);
  });

  it('permission denied (NotAllowedError) → errorMessage set, ready false', async () => {
    const err = new DOMException('Permission denied', 'NotAllowedError');
    const getUserMedia = vi.fn().mockRejectedValue(err);
    Object.defineProperty(navigator, 'mediaDevices', {
      value: { getUserMedia },
      configurable: true,
      writable: true,
    });
    const { result } = renderHook(() => useCamera());
    await waitFor(() => expect(result.current.errorMessage).not.toBeNull());
    expect(result.current.ready).toBe(false);
    expect(result.current.errorMessage).toMatch(/Permission denied|denied/i);
  });

  it('capture before ready → null', async () => {
    const never = new Promise<MediaStream>(() => {});
    const getUserMedia = vi.fn().mockReturnValue(never);
    Object.defineProperty(navigator, 'mediaDevices', {
      value: { getUserMedia },
      configurable: true,
      writable: true,
    });
    const { result } = renderHook(() => useCamera());
    // ready is false initially; capture must resolve null without throwing
    let out: unknown = 'unset';
    await act(async () => {
      out = await result.current.capture();
    });
    expect(out).toBeNull();
    expect(result.current.ready).toBe(false);
  });

  it('cleanup stops tracks on unmount', async () => {
    const { stream, stop } = mockStream();
    let resolveGum!: (s: MediaStream) => void;
    const gumPromise = new Promise<MediaStream>((r) => {
      resolveGum = r;
    });
    const getUserMedia = vi.fn().mockReturnValue(gumPromise);
    Object.defineProperty(navigator, 'mediaDevices', {
      value: { getUserMedia },
      configurable: true,
      writable: true,
    });
    const { unmount } = renderHook(() => useCamera());
    // Resolve then unmount quickly: both paths must stop tracks
    await act(async () => {
      resolveGum(stream);
      await gumPromise;
    });
    unmount();
    // After unmount the stream tracks must have been stopped
    // (either via cancelled-path or cleanup-path)
    await waitFor(() => expect(stop).toHaveBeenCalled());
  });
});
