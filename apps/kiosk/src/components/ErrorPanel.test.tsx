import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ErrorPanel } from './ErrorPanel';
import { Button } from './Button';

describe('ErrorPanel (guest-facing)', () => {
  it('renders title and message, never raw codes', () => {
    render(<ErrorPanel title="Something went wrong" message="Please try again" />);
    expect(screen.getByRole('alert')).toBeTruthy();
    expect(screen.getByText('Something went wrong')).toBeTruthy();
    expect(screen.getByText('Please try again')).toBeTruthy();
  });

  it('does not render a code element', () => {
    const { container } = render(<ErrorPanel title="Oops" message="Try again" />);
    expect(container.querySelector('.error-panel__code')).toBeNull();
  });

  it('retry callback fires when retry button clicked', () => {
    const onRetry = vi.fn();
    render(
      <ErrorPanel
        title="oops"
        message="try again"
        retry={
          <Button onClick={onRetry}>
            Retry
          </Button>
        }
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('renders retry and reset actions together', () => {
    const onRetry = vi.fn();
    const onReset = vi.fn();
    render(
      <ErrorPanel
        title="failed"
        message="sorry"
        retry={<button onClick={onRetry}>Try again</button>}
        reset={<button onClick={onReset}>Start over</button>}
      />,
    );
    fireEvent.click(screen.getByText('Try again'));
    fireEvent.click(screen.getByText('Start over'));
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(onReset).toHaveBeenCalledTimes(1);
  });

  it('supports ReactNode message', () => {
    render(
      <ErrorPanel
        title="Failed"
        message={
          <span>
            Failed with <strong>details</strong>
          </span>
        }
      />,
    );
    expect(screen.getByText(/Failed with/)).toBeTruthy();
    expect(screen.getByText('details')).toBeTruthy();
  });
});
