import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { StageOverlay } from './StageOverlay';
import type { ReelItem, ReelPolicyConfig } from '@aura/reel';

const items: ReelItem[] = [
  { id: 'a', kind: 'curated', src: '/videos/a.mp4', duration_sec: 10, title: 'Alpha' },
  { id: 'g1', kind: 'generated', src: '/generated/g1.mp4', duration_sec: 4, title: 'Gen 1' },
];

const policy: ReelPolicyConfig = { defaultInsert: 'queued' };

describe('StageOverlay', () => {
  it('renders current title and kind', () => {
    render(
      <StageOverlay
        current={items[0]!}
        playlist={items}
        policy={policy}
        onPolicyChange={() => {}}
        wsStatus="open"
        isFullscreen={false}
        onToggleFullscreen={() => {}}
      />,
    );
    expect(screen.getByText(/Alpha/)).toBeTruthy();
    expect(screen.getByText(/curated/)).toBeTruthy();
  });

  it('renders idle when no current', () => {
    render(
      <StageOverlay
        current={null}
        playlist={[]}
        policy={policy}
        onPolicyChange={() => {}}
        wsStatus="connecting"
        isFullscreen={false}
        onToggleFullscreen={() => {}}
      />,
    );
    expect(screen.getByText(/Idle/)).toBeTruthy();
  });

  it('renders ws status', () => {
    render(
      <StageOverlay
        current={null}
        playlist={[]}
        policy={policy}
        onPolicyChange={() => {}}
        wsStatus="open"
        isFullscreen={false}
        onToggleFullscreen={() => {}}
      />,
    );
    expect(screen.getByText(/WS: open/)).toBeTruthy();
  });

  it('renders playlist dots + count', () => {
    const { container } = render(
      <StageOverlay
        current={items[0]!}
        playlist={items}
        policy={policy}
        onPolicyChange={() => {}}
        wsStatus="open"
        isFullscreen={false}
        onToggleFullscreen={() => {}}
      />,
    );
    expect(container.querySelectorAll('.stage-playlist__dot').length).toBe(2);
    expect(screen.getByText('2 items')).toBeTruthy();
    // active dot for current
    expect(container.querySelector('.stage-playlist__dot--active')).not.toBeNull();
    // generated marker
    expect(container.querySelector('.stage-playlist__dot--generated')).not.toBeNull();
  });

  it('empty playlist shows 0 items', () => {
    render(
      <StageOverlay
        current={null}
        playlist={[]}
        policy={policy}
        onPolicyChange={() => {}}
        wsStatus="open"
        isFullscreen={false}
        onToggleFullscreen={() => {}}
      />,
    );
    expect(screen.getByText('0 items')).toBeTruthy();
  });

  it('policy change fires onPolicyChange', () => {
    const onPolicyChange = vi.fn();
    render(
      <StageOverlay
        current={null}
        playlist={[]}
        policy={policy}
        onPolicyChange={onPolicyChange}
        wsStatus="open"
        isFullscreen={false}
        onToggleFullscreen={() => {}}
      />,
    );
    fireEvent.change(screen.getByLabelText('Insert policy'), { target: { value: 'priority' } });
    expect(onPolicyChange).toHaveBeenCalledWith({ defaultInsert: 'priority' });
  });

  it('fullscreen toggle button', () => {
    const onToggle = vi.fn();
    const { rerender } = render(
      <StageOverlay
        current={null}
        playlist={[]}
        policy={policy}
        onPolicyChange={() => {}}
        wsStatus="open"
        isFullscreen={false}
        onToggleFullscreen={onToggle}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Fullscreen' }));
    expect(onToggle).toHaveBeenCalledTimes(1);
    rerender(
      <StageOverlay
        current={null}
        playlist={[]}
        policy={policy}
        onPolicyChange={() => {}}
        wsStatus="open"
        isFullscreen={true}
        onToggleFullscreen={onToggle}
      />,
    );
    expect(screen.getByRole('button', { name: 'Exit Fullscreen' })).toBeTruthy();
  });

  it('error-ish ws status still renders', () => {
    render(
      <StageOverlay
        current={items[1]!}
        playlist={items}
        policy={policy}
        onPolicyChange={() => {}}
        wsStatus="error"
        isFullscreen={false}
        onToggleFullscreen={() => {}}
      />,
    );
    expect(screen.getByText(/WS: error/)).toBeTruthy();
  });
});
