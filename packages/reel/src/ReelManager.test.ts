import { describe, it, expect, beforeEach } from 'vitest';
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

describe('ReelManager — basic playlist', () => {
  it('starts empty', () => {
    const m = new ReelManager({ policy: basePolicy });
    expect(m.getCurrent()).toBeNull();
    expect(m.isEmpty()).toBe(true);
    expect(m.size()).toBe(0);
  });

  it('loops continuously', () => {
    const m = new ReelManager({ policy: basePolicy, initialPlaylist: [curated('a'), curated('b')] });
    expect(m.getCurrent()?.id).toBe('a');
    m.advance();
    expect(m.getCurrent()?.id).toBe('b');
    m.advance();
    expect(m.getCurrent()?.id).toBe('a');
    m.advance();
    expect(m.getCurrent()?.id).toBe('b');
  });

  it('peekNext returns next without advancing', () => {
    const m = new ReelManager({ policy: basePolicy, initialPlaylist: [curated('a'), curated('b'), curated('c')] });
    expect(m.peekNext()?.id).toBe('b');
    expect(m.getCurrent()?.id).toBe('a');
  });

  it('preload src is next item src', () => {
    const m = new ReelManager({ policy: basePolicy, initialPlaylist: [curated('a'), curated('b')] });
    expect(m.getPreloadSrc()).toBe('/videos/b.mp4');
    m.advance();
    expect(m.getPreloadSrc()).toBe('/videos/a.mp4');
  });

  it('setPlaylist preserves current by id', () => {
    const m = new ReelManager({ policy: basePolicy, initialPlaylist: [curated('a'), curated('b')] });
    m.advance(); // now b
    m.setPlaylist([curated('b'), curated('c'), curated('a')]);
    expect(m.getCurrent()?.id).toBe('b');
  });
});

describe('ReelManager — policies', () => {
  it('queued appends to tail', () => {
    const m = new ReelManager({ policy: { defaultInsert: 'queued' }, initialPlaylist: [curated('a'), curated('b')] });
    // current is a (index 0)
    const res = m.enqueue(generated('g1'));
    expect(res.accepted).toBe(true);
    expect(res.shouldInterrupt).toBe(false);
    expect(m.getPlaylist().map((i) => i.id)).toEqual(['a', 'b', 'g1']);
    expect(m.getCurrent()?.id).toBe('a'); // no interruption
  });

  it('priority inserts after current', () => {
    const m = new ReelManager({ policy: { defaultInsert: 'priority' }, initialPlaylist: [curated('a'), curated('b')] });
    m.enqueue(generated('g1'));
    expect(m.getPlaylist().map((i) => i.id)).toEqual(['a', 'g1', 'b']);
  });

  it('immediate inserts after current and signals interruption', () => {
    const m = new ReelManager({ policy: { defaultInsert: 'immediate' }, initialPlaylist: [curated('a'), curated('b')] });
    const res = m.enqueue(generated('g1'));
    expect(res.shouldInterrupt).toBe(true);
    expect(m.getPlaylist().map((i) => i.id)).toEqual(['a', 'g1', 'b']);
  });

  it('play-once inserts after current and removes after playback', () => {
    const m = new ReelManager({ policy: { defaultInsert: 'play-once' }, initialPlaylist: [curated('a'), curated('b')] });
    m.enqueue(generated('g1'));
    expect(m.getPlaylist().map((i) => i.id)).toEqual(['a', 'g1', 'b']);
    // Advance from a -> g1
    m.advance();
    expect(m.getCurrent()?.id).toBe('g1');
    // Advance from g1 -> should remove g1 then go to b
    m.advance();
    expect(m.getCurrent()?.id).toBe('b');
    expect(m.getPlaylist().some((i) => i.id === 'g1')).toBe(false);
  });

  it('explicit policy overrides default', () => {
    const m = new ReelManager({ policy: { defaultInsert: 'queued' }, initialPlaylist: [curated('a'), curated('b')] });
    // default is queued, but we pass immediate
    const res = m.enqueue(generated('g1'), 'immediate');
    expect(res.shouldInterrupt).toBe(true);
    expect(m.getPlaylist()[1].id).toBe('g1');
  });

  it('duplicate id is rejected', () => {
    const m = new ReelManager({ policy: basePolicy, initialPlaylist: [curated('a')] });
    const res = m.enqueue(curated('a'));
    expect(res.accepted).toBe(false);
    expect(res.reason).toBe('duplicate');
  });

  it('maxGeneratedInQueue is enforced', () => {
    const m = new ReelManager({
      policy: { defaultInsert: 'queued', maxGeneratedInQueue: 1 },
      initialPlaylist: [curated('a')],
    });
    expect(m.enqueue(generated('g1')).accepted).toBe(true);
    expect(m.enqueue(generated('g2')).accepted).toBe(false);
    expect(m.enqueue(generated('g2')).reason).toBe('queue_full');
  });

  it('handleNewVideo respects default policy without interruption', () => {
    const m = new ReelManager({ policy: { defaultInsert: 'queued' }, initialPlaylist: [curated('a')] });
    const before = m.getCurrent()?.id;
    m.handleNewVideo(generated('g1'));
    expect(m.getCurrent()?.id).toBe(before);
    expect(m.getPlaylist().at(-1)?.id).toBe('g1');
  });
});

describe('ReelManager — error recovery', () => {
  it('handleError removes faulty current and advances', () => {
    const m = new ReelManager({ policy: basePolicy, initialPlaylist: [curated('a'), curated('b'), curated('c')] });
    // current is a
    const next = m.handleError('a');
    expect(next?.id).toBe('b');
    expect(m.getPlaylist().some((i) => i.id === 'a')).toBe(false);
  });

  it('handleError on non-current keeps current', () => {
    const m = new ReelManager({ policy: basePolicy, initialPlaylist: [curated('a'), curated('b'), curated('c')] });
    m.handleError('c');
    expect(m.getCurrent()?.id).toBe('a');
    expect(m.size()).toBe(2);
  });

  it('handleError on missing id is no-op', () => {
    const m = new ReelManager({ policy: basePolicy, initialPlaylist: [curated('a')] });
    const cur = m.handleError('missing');
    expect(cur?.id).toBe('a');
  });

  it('jumpTo moves current', () => {
    const m = new ReelManager({ policy: basePolicy, initialPlaylist: [curated('a'), curated('b'), curated('c')] });
    m.jumpTo('c');
    expect(m.getCurrent()?.id).toBe('c');
    m.advance();
    expect(m.getCurrent()?.id).toBe('a'); // loops
  });

  it('jumpTo missing returns null and keeps current', () => {
    const m = new ReelManager({ policy: basePolicy, initialPlaylist: [curated('a'), curated('b')] });
    expect(m.jumpTo('missing')).toBeNull();
    expect(m.getCurrent()?.id).toBe('a');
  });
});

describe('ReelManager — edge cases', () => {
  it('advance on empty returns null', () => {
    const m = new ReelManager({ policy: basePolicy });
    expect(m.advance()).toBeNull();
  });

  it('enqueue on empty sets current to new item', () => {
    const m = new ReelManager({ policy: basePolicy });
    m.enqueue(curated('a'));
    expect(m.getCurrent()?.id).toBe('a');
  });

  it('play-once on single item playlist removes after advance and becomes empty', () => {
    const m = new ReelManager({ policy: { defaultInsert: 'play-once' }, initialPlaylist: [] });
    m.enqueue(generated('g1'));
    expect(m.getCurrent()?.id).toBe('g1');
    const next = m.advance();
    expect(next).toBeNull();
    expect(m.isEmpty()).toBe(true);
  });

  it('setPolicy updates without resetting playlist', () => {
    const m = new ReelManager({ policy: { defaultInsert: 'queued' }, initialPlaylist: [curated('a')] });
    m.setPolicy({ defaultInsert: 'priority' });
    expect(m.getPolicy().defaultInsert).toBe('priority');
    expect(m.getCurrent()?.id).toBe('a');
  });
});
