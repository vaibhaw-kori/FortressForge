import { describe, it, expect } from 'vitest';
import { ReelManager, ReelItem, ReelPolicyConfig } from './ReelManager';

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

const basePolicy: ReelPolicyConfig = { defaultInsert: 'queued' };

describe('ReelManager — failure recovery', () => {
  it('corrupt item (empty src) is rejected, never queued', () => {
    const m = new ReelManager({ policy: basePolicy, initialPlaylist: [curated('a')] });
    const res = m.enqueue({ id: 'bad', kind: 'generated', src: '', duration_sec: 4 });
    expect(res.accepted).toBe(false);
    expect(res.reason).toMatch(/invalid_src|corrupt|invalid/i);
    expect(m.getPlaylist().some((i) => i.id === 'bad')).toBe(false);
    expect(m.getCurrent()?.id).toBe('a');
  });

  it('corrupt item (whitespace src) is rejected', () => {
    const m = new ReelManager({ policy: basePolicy, initialPlaylist: [] });
    const res = m.enqueue({ id: 'bad2', kind: 'generated', src: '   ', duration_sec: 4 });
    expect(res.accepted).toBe(false);
    expect(m.isEmpty()).toBe(true);
  });

  it('corrupt item (missing id) is rejected', () => {
    const m = new ReelManager({ policy: basePolicy, initialPlaylist: [curated('a')] });
    const res = m.enqueue({ id: '', kind: 'generated', src: '/generated/x.mp4', duration_sec: 4 });
    expect(res.accepted).toBe(false);
    expect(m.size()).toBe(1);
  });

  it('duplicate id is rejected', () => {
    const m = new ReelManager({ policy: basePolicy, initialPlaylist: [curated('a')] });
    const res = m.enqueue(curated('a'));
    expect(res.accepted).toBe(false);
    expect(res.reason).toBe('duplicate');
    expect(m.size()).toBe(1);
  });

  it('queue_full when maxGeneratedInQueue reached', () => {
    const m = new ReelManager({
      policy: { defaultInsert: 'queued', maxGeneratedInQueue: 1 },
      initialPlaylist: [curated('a')],
    });
    expect(m.enqueue(generated('g1')).accepted).toBe(true);
    const res = m.enqueue(generated('g2'));
    expect(res.accepted).toBe(false);
    expect(res.reason).toBe('queue_full');
  });

  it('faulty current removed and playback advances', () => {
    const m = new ReelManager({
      policy: basePolicy,
      initialPlaylist: [curated('a'), curated('b'), curated('c')],
    });
    const next = m.handleError('a');
    expect(next?.id).toBe('b');
    expect(m.getCurrent()?.id).toBe('b');
    expect(m.getPlaylist().map((i) => i.id)).toEqual(['b', 'c']);
  });

  it('playback failure recovery: sequential errors drain to next good item', () => {
    const m = new ReelManager({
      policy: basePolicy,
      initialPlaylist: [curated('a'), curated('b'), curated('c')],
    });
    m.handleError('a'); // → b
    expect(m.getCurrent()?.id).toBe('b');
    m.handleError('b'); // → c
    expect(m.getCurrent()?.id).toBe('c');
    expect(m.size()).toBe(1);
  });

  it('handleError on last item wraps to first', () => {
    const m = new ReelManager({ policy: basePolicy, initialPlaylist: [curated('a'), curated('b')] });
    m.jumpTo('b');
    const next = m.handleError('b');
    expect(next?.id).toBe('a');
  });

  it('handleError on missing id is no-op', () => {
    const m = new ReelManager({ policy: basePolicy, initialPlaylist: [curated('a')] });
    const cur = m.handleError('ghost');
    expect(cur?.id).toBe('a');
    expect(m.size()).toBe(1);
  });

  it('failed enqueue does not bump version or disturb playback', () => {
    const m = new ReelManager({ policy: basePolicy, initialPlaylist: [curated('a'), curated('b')] });
    const v0 = m.getVersion();
    m.enqueue({ id: 'x', kind: 'generated', src: '', duration_sec: 4 });
    m.enqueue(curated('a')); // duplicate
    expect(m.getVersion()).toBe(v0);
    expect(m.getCurrent()?.id).toBe('a');
  });
});
