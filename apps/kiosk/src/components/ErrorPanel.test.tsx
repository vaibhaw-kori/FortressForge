import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ErrorPanel } from './ErrorPanel';
import { Button } from './Button';

describe('ErrorPanel', () => {
  it('renders message and code', () => {
    render(<ErrorPanel code="upload_failed" message="Upload failed, please try again" />);
    expect(screen.getByRole('alert')).toBeTruthy();
    expect(screen.getByText('upload_failed')).toBeTruthy();
    expect(screen.getByText('Upload failed, please try again')).toBeTruthy();
  });

  it('renders without code when not provided', () => {
    const { container } = render(<ErrorPanel message="Something broke" />);
    expect(container.querySelector('.error-panel__code')).toBeNull();
    expect(screen.getByText('Something broke')).toBeTruthy();
  });

  it('retry callback fires when retry button clicked', () => {
    const onRetry = vi.fn();
    render(
      <ErrorPanel
        code="ERR"
        message="oops"
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
        message="failed"
        retry={<button onClick={onRetry}>Try again</button>}
        reset={<button onClick={onReset}>Start over</button>}
      />,
    );
    fireEvent.click(screen.getByText('Try again'));
    fireEvent.click(screen.getByText('Start over'));
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(onReset).toHaveBeenCalledTimes(1);
  });

  it('camera-denied variant shows permission message', () => {
    render(
      <ErrorPanel
        code="camera_denied"
        message="Camera access denied — please allow camera access"
        retry={<button>Retry</button>}
      />,
    );
    expect(screen.getByText(/Camera access denied/)).toBeTruthy();
    expect(screen.getByText('camera_denied')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy();
  });

  it('camera-unavailable variant shows API message', () => {
    render(
      <ErrorPanel
        code="camera_unavailable"
        message="Camera API not available on this device"
        retry={<button>Retry</button>}
      />,
    );
    expect(screen.getByText(/Camera API not available/)).toBeTruthy();
    expect(screen.getByText('camera_unavailable')).toBeTruthy();
  });

  it('supports ReactNode message', () => {
    render(
      <ErrorPanel
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
