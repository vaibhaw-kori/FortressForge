import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { CountdownDial } from './CountdownDial';

describe('CountdownDial', () => {
  it('renders remaining value', () => {
    render(<CountdownDial total={4} remaining={4} />);
    expect(screen.getByText('4')).toBeTruthy();
  });

  it('renders each remaining value through countdown', () => {
    for (const remaining of [3, 2, 1]) {
      const { unmount } = render(<CountdownDial total={4} remaining={remaining} />);
      expect(screen.getByText(String(remaining))).toBeTruthy();
      unmount();
    }
  });

  it('done state shows 0', () => {
    render(<CountdownDial total={4} remaining={0} />);
    expect(screen.getByText('0')).toBeTruthy();
    expect(screen.getByLabelText('0 seconds remaining')).toBeTruthy();
  });

  it('exposes accessible remaining label', () => {
    render(<CountdownDial total={5} remaining={2} />);
    expect(screen.getByLabelText('2 seconds remaining')).toBeTruthy();
  });

  it('ring offset is full-circle when remaining is 0', () => {
    const { container } = render(<CountdownDial total={4} remaining={0} />);
    const fg = container.querySelector('.countdown__fg') as SVGCircleElement | null;
    expect(fg).not.toBeNull();
    const dasharray = Number(fg!.getAttribute('stroke-dasharray'));
    const offset = Number(fg!.getAttribute('stroke-dashoffset'));
    // At 0 remaining, offset == full circumference
    expect(Math.abs(offset - dasharray)).toBeLessThan(1e-6);
  });

  it('ring offset is zero when remaining equals total', () => {
    const { container } = render(<CountdownDial total={4} remaining={4} />);
    const fg = container.querySelector('.countdown__fg') as SVGCircleElement | null;
    expect(fg).not.toBeNull();
    expect(Number(fg!.getAttribute('stroke-dashoffset'))).toBeCloseTo(0, 6);
  });

  it('handles total 0 without NaN', () => {
    const { container } = render(<CountdownDial total={0} remaining={0} />);
    expect(screen.getByText('0')).toBeTruthy();
    const fg = container.querySelector('.countdown__fg') as SVGCircleElement | null;
    expect(fg).not.toBeNull();
    expect(Number.isNaN(Number(fg!.getAttribute('stroke-dashoffset')))).toBe(false);
  });
});
