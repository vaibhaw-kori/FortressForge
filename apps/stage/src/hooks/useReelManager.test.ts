import { describe, expect, it } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useReelManager } from './useReelManager';
import type { ReelItem } from '@aura/reel';

const curated = (id: string, src = `/videos/${id}.mp4`): ReelItem => ({
  id,
  kind: 'curated',
  src,
  duration_sec: 10,
  title: id,
});
const generated = (id: string, src = `/generated/${id}.mp4`): ReelItem => ({
  id,
  kind: 'generated',
  src,
  duration_sec: 4,
  title: id,
});

describe('useReelManager', () => {
  it('initializes with playlist and current', () => {
    const { result } = renderHook(() =>
      useReelManager({ policy: { defaultInsert: 'queued' }, initialPlaylist: [curated('a'), curated('b')] }),
    );
    expect(result.current.current?.id).toBe('a');
    expect(result.current.playlist.map((i) => i.id)).toEqual(['a', 'b']);
  });

  it('enqueue generated appends without interrupting', () => {
    const { result } = renderHook(() =>
      useReelManager({ policy: { defaultInsert: 'queued' }, initialPlaylist: [curated('a')] }),
    );
    let res!: { accepted: boolean; reason: string; shouldInterrupt: boolean };
    act(() => {
      res = result.current.enqueue(generated('g1'));
    });
    expect(res.accepted).toBe(true);
    expect(result.current.playlist.map((i) => i.id)).toEqual(['a', 'g1']);
    expect(result.current.current?.id).toBe('a');
  });

  it('play-next advances current', () => {
    const { result } = renderHook(() =>
      useReelManager({ policy: { defaultInsert: 'queued' }, initialPlaylist: [curated('a'), curated('b')] }),
    );
    act(() => {
      result.current.advance();
    });
    expect(result.current.current?.id).toBe('b');
    act(() => {
      result.current.advance();
    });
    expect(result.current.current?.id).toBe('a'); // loops
  });

  it('handleError removes faulty current and advances (playback failure recovery)', () => {
    const { result } = renderHook(() =>
      useReelManager({
        policy: { defaultInsert: 'queued' },
        initialPlaylist: [curated('a'), curated('b'), curated('c')],
      }),
    );
    expect(result.current.current?.id).toBe('a');
    let next!: unknown;
    act(() => {
      next = result.current.handleError('a');
    });
    expect((next as ReelItem)?.id).toBe('b');
    expect(result.current.current?.id).toBe('b');
    expect(result.current.playlist.some((i) => i.id === 'a')).toBe(false);
  });

  it('handleError on non-current keeps current', () => {
    const { result } = renderHook(() =>
      useReelManager({
        policy: { defaultInsert: 'queued' },
        initialPlaylist: [curated('a'), curated('b')],
      }),
    );
    act(() => {
      result.current.handleError('b');
    });
    expect(result.current.current?.id).toBe('a');
    expect(result.current.playlist.length).toBe(1);
  });

  it('empty playlist: current null, advance null, preload null', () => {
    const { result } = renderHook(() =>
      useReelManager({ policy: { defaultInsert: 'queued' }, initialPlaylist: [] }),
    );
    expect(result.current.current).toBeNull();
    expect(result.current.playlist).toEqual([]);
    let n!: unknown;
    act(() => {
      n = result.current.advance();
    });
    expect(n).toBeNull();
    expect(result.current.preloadSrc).toBeNull();
  });

  it('version bumps on mutation', () => {
    const { result } = renderHook(() =>
      useReelManager({ policy: { defaultInsert: 'queued' }, initialPlaylist: [curated('a')] }),
    );
    const v0 = result.current.version;
    act(() => {
      result.current.enqueue(generated('g1'));
    });
    expect(result.current.version).toBeGreaterThan(v0);
  });
});
