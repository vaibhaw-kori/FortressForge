import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { StageOverlay } from './StageOverlay';
import type { ReelItem } from '@aura/reel';

const items: ReelItem[] = [
  { id: 'a', kind: 'curated', src: '/videos/a.mp4', duration_sec: 10, title: 'Alpha' },
  { id: 'g1', kind: 'generated', src: '/generated/g1.mp4', duration_sec: 4, title: 'Gen 1' },
];

describe('StageOverlay (presentation chrome)', () => {
  it('renders progress dots with active + generated markers, no text chrome', () => {
    const { container } = render(<StageOverlay current={items[0]!} playlist={items} />);
    expect(container.querySelectorAll('.stage-playlist__dot').length).toBe(2);
    expect(container.querySelector('.stage-playlist__dot--active')).not.toBeNull();
    expect(container.querySelector('.stage-playlist__dot--generated')).not.toBeNull();
    // No developer chrome: no titles, counts, status, or controls
    const text = container.textContent ?? '';
    for (const banned of ['Alpha', 'Gen 1', 'curated', 'generated', 'items', 'WS:', 'Idle', 'Fullscreen', 'Queued']) {
      expect(text).not.toContain(banned);
    }
  });

  it('renders nothing textual when idle', () => {
    const { container } = render(<StageOverlay current={null} playlist={[]} />);
    expect(container.querySelector('.stage-overlay')).not.toBeNull();
    expect(container.querySelectorAll('.stage-playlist__dot').length).toBe(0);
    expect(container.querySelector('button, select')).toBeNull();
  });

  it('hidden prop fades the chrome', () => {
    const { container, rerender } = render(<StageOverlay current={items[0]!} playlist={items} />);
    expect(container.querySelector('.stage-overlay--hidden')).toBeNull();
    rerender(<StageOverlay current={items[0]!} playlist={items} hidden />);
    expect(container.querySelector('.stage-overlay--hidden')).not.toBeNull();
  });

  it('switching current moves the active dot', () => {
    const { container, rerender } = render(<StageOverlay current={items[0]!} playlist={items} />);
    const dots = () => Array.from(container.querySelectorAll('.stage-playlist__dot'));
    expect(dots()[0]!.className).toContain('stage-playlist__dot--active');
    rerender(<StageOverlay current={items[1]!} playlist={items} />);
    expect(dots()[1]!.className).toContain('stage-playlist__dot--active');
  });
});
