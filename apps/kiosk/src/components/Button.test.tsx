import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Button } from './Button';

describe('Button', () => {
  it('renders children', () => {
    render(<Button>Continue</Button>);
    expect(screen.getByRole('button', { name: 'Continue' })).toBeTruthy();
  });

  it('fires onClick', () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Tap me</Button>);
    fireEvent.click(screen.getByRole('button', { name: 'Tap me' }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('applies primary default class', () => {
    render(<Button>Hi</Button>);
    const btn = screen.getByRole('button', { name: 'Hi' });
    expect(btn.className).toContain('btn');
  });

  it('applies ghost variant class', () => {
    render(<Button variant="ghost">Ghost</Button>);
    expect(screen.getByRole('button', { name: 'Ghost' }).className).toContain('btn--ghost');
  });

  it('applies danger variant class', () => {
    render(<Button variant="danger">Delete</Button>);
    expect(screen.getByRole('button', { name: 'Delete' }).className).toContain('btn--danger');
  });

  it('applies large size class', () => {
    render(<Button size="lg">Big</Button>);
    expect(screen.getByRole('button', { name: 'Big' }).className).toContain('btn--lg');
  });

  it('forwards disabled attribute', () => {
    render(<Button disabled>Off</Button>);
    expect((screen.getByRole('button', { name: 'Off' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('merges custom className', () => {
    render(<Button className="extra">X</Button>);
    expect(screen.getByRole('button', { name: 'X' }).className).toContain('extra');
  });
});
