import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { VideoStage } from './VideoStage';
import type { ReelItem } from '@aura/reel';

const item = (id: string, src = `/videos/${id}.mp4`): ReelItem => ({
  id,
  kind: 'curated',
  src,
  duration_sec: 10,
  title: id,
});

describe('VideoStage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    // jsdom has no media implementation — stub play/load/pause.
    vi.spyOn(window.HTMLMediaElement.prototype, 'play').mockImplementation(() => Promise.resolve());
    vi.spyOn(window.HTMLMediaElement.prototype, 'load').mockImplementation(() => {});
    vi.spyOn(window.HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
    document.head.querySelectorAll('link[rel="preload"]').forEach((el) => el.remove());
  });

  it('empty state shows ambient brand mark, no developer text', () => {
    const { container } = render(<VideoStage current={null} preloadSrc={null} onEnded={() => {}} onError={() => {}} />);
    expect(container.querySelector('.video-stage__ambient')).not.toBeNull();
    const text = container.textContent ?? '';
    for (const banned of ['No content', 'waiting for reel', 'reel…', 'Loading']) {
      expect(text).not.toContain(banned);
    }
  });

  it('renders video src after current is set', async () => {
    const onEnded = vi.fn();
    const onError = vi.fn();
    const { container } = render(
      <VideoStage current={item('a')} preloadSrc={null} onEnded={onEnded} onError={onError} />,
    );
    await waitFor(() => {
      const vids = container.querySelectorAll('video');
      const srcs = Array.from(vids).map((v) => v.getAttribute('src'));
      expect(srcs).toContain('/videos/a.mp4');
    });
  });

  it('marks one video active after load', async () => {
    const { container } = render(
      <VideoStage current={item('a')} preloadSrc={null} onEnded={() => {}} onError={() => {}} />,
    );
    await waitFor(() => {
      expect(container.querySelector('.video-stage__video--active')).not.toBeNull();
    });
  });

  it('playback failure (video onError) calls onError with current id', async () => {
    const onError = vi.fn();
    const { container } = render(
      <VideoStage current={item('bad')} preloadSrc={null} onEnded={() => {}} onError={onError} />,
    );
    // Wait for the active video to be determined
    let active: HTMLVideoElement | null = null;
    await waitFor(() => {
      active = container.querySelector('.video-stage__video--active') as HTMLVideoElement | null;
      expect(active).not.toBeNull();
    });
    fireEvent.error(active!);
    expect(onError).toHaveBeenCalledWith('bad');
  });

  it('error on inactive video is ignored', async () => {
    const onError = vi.fn();
    const { container } = render(
      <VideoStage current={item('a')} preloadSrc={null} onEnded={() => {}} onError={onError} />,
    );
    await waitFor(() => {
      expect(container.querySelector('.video-stage__video--active')).not.toBeNull();
    });
    const videos = container.querySelectorAll('video');
    // Find the inactive one
    const inactive = Array.from(videos).find((v) => !v.classList.contains('video-stage__video--active'));
    expect(inactive).toBeTruthy();
    fireEvent.error(inactive!);
    expect(onError).not.toHaveBeenCalled();
  });

  it('onEnded advances (calls onEnded handler)', async () => {
    const onEnded = vi.fn();
    const { container } = render(
      <VideoStage current={item('a')} preloadSrc={null} onEnded={onEnded} onError={() => {}} />,
    );
    let active: HTMLVideoElement | null = null;
    await waitFor(() => {
      active = container.querySelector('.video-stage__video--active') as HTMLVideoElement | null;
      expect(active).not.toBeNull();
    });
    fireEvent.ended(active!);
    expect(onEnded).toHaveBeenCalledTimes(1);
  });

  it('preload src creates preload link', async () => {
    render(
      <VideoStage current={item('a')} preloadSrc="/videos/b.mp4" onEnded={() => {}} onError={() => {}} />,
    );
    await waitFor(() => {
      const link = document.head.querySelector('link[rel="preload"][href="/videos/b.mp4"]');
      expect(link).not.toBeNull();
    });
  });

  it('switching current loads next video', async () => {
    const onError = vi.fn();
    const { container, rerender } = render(
      <VideoStage current={item('a')} preloadSrc={null} onEnded={() => {}} onError={onError} />,
    );
    await waitFor(() => {
      const srcs = Array.from(container.querySelectorAll('video')).map((v) => v.getAttribute('src'));
      expect(srcs).toContain('/videos/a.mp4');
    });
    rerender(<VideoStage current={item('b')} preloadSrc={null} onEnded={() => {}} onError={onError} />);
    await waitFor(() => {
      const srcs = Array.from(container.querySelectorAll('video')).map((v) => v.getAttribute('src'));
      expect(srcs).toContain('/videos/b.mp4');
    });
  });
});
