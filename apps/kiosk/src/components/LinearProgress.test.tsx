import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LinearProgress } from './LinearProgress';

describe('LinearProgress', () => {
  it('renders progressbar role', () => {
    render(<LinearProgress progress={0.5} />);
    expect(screen.getByRole('progressbar')).toBeTruthy();
  });

  it('sets width from progress', () => {
    const { container } = render(<LinearProgress progress={0.5} />);
    const fill = container.querySelector('.linear__fill') as HTMLElement | null;
    expect(fill).not.toBeNull();
    expect(fill!.style.width).toBe('50%');
  });

  it('clamps below 0', () => {
    const { container } = render(<LinearProgress progress={-2} />);
    const fill = container.querySelector('.linear__fill') as HTMLElement | null;
    expect(fill!.style.width).toBe('0%');
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('0');
  });

  it('clamps above 1', () => {
    const { container } = render(<LinearProgress progress={5} />);
    const fill = container.querySelector('.linear__fill') as HTMLElement | null;
    expect(fill!.style.width).toBe('100%');
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('100');
  });

  it('reports rounded aria-valuenow', () => {
    render(<LinearProgress progress={0.456} />);
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('46');
  });
});
