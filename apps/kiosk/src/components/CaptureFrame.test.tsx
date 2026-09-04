import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { createRef } from 'react';
import { CaptureFrame } from './CaptureFrame';

describe('CaptureFrame', () => {
  it('loading state shows warming-up text when not ready and no error', () => {
    const ref = createRef<HTMLVideoElement>();
    render(<CaptureFrame videoRef={ref} ready={false} errorMessage={null} />);
    expect(screen.getByText('Camera warming up…')).toBeTruthy();
  });

  it('error state shows errorMessage when not ready', () => {
    const ref = createRef<HTMLVideoElement>();
    render(<CaptureFrame videoRef={ref} ready={false} errorMessage="Camera API not available" />);
    expect(screen.getByText('Camera API not available')).toBeTruthy();
  });

  it('permission-denied error variant', () => {
    const ref = createRef<HTMLVideoElement>();
    render(
      <CaptureFrame videoRef={ref} ready={false} errorMessage="Permission denied" />,
    );
    expect(screen.getByText('Permission denied')).toBeTruthy();
  });

  it('ready state renders video element', () => {
    const ref = createRef<HTMLVideoElement>();
    const { container } = render(<CaptureFrame videoRef={ref} ready={true} errorMessage={null} />);
    const video = container.querySelector('video.capture-frame__video');
    expect(video).not.toBeNull();
  });

  it('ready state renders hint text when provided', () => {
    const ref = createRef<HTMLVideoElement>();
    render(
      <CaptureFrame videoRef={ref} ready={true} errorMessage={null} hintText="Center your face" />,
    );
    expect(screen.getByText('Center your face')).toBeTruthy();
  });

  it('ready state omits hint when not provided', () => {
    const ref = createRef<HTMLVideoElement>();
    const { container } = render(<CaptureFrame videoRef={ref} ready={true} errorMessage={null} />);
    expect(container.querySelector('.capture-frame__hint')).toBeNull();
  });

  it('applies landscape modifier class', () => {
    const ref = createRef<HTMLVideoElement>();
    const { container } = render(
      <CaptureFrame videoRef={ref} ready={true} errorMessage={null} aspect="landscape" />,
    );
    expect(container.querySelector('.capture-frame--landscape')).not.toBeNull();
  });

  it('portrait (default) has no landscape modifier', () => {
    const ref = createRef<HTMLVideoElement>();
    const { container } = render(<CaptureFrame videoRef={ref} ready={true} errorMessage={null} />);
    expect(container.querySelector('.capture-frame--landscape')).toBeNull();
  });
});
