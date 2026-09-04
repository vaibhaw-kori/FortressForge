/**
 * Real curated videos — independent from backend.
 * These are real MP4 files hosted on public CDNs, suitable for a premium installation.
 * The stage runs even if the backend is unreachable: it falls back to these.
 *
 * Duration estimates are conservative; the player uses actual video duration.
 */
import type { ReelItem } from '@aura/reel';

export const CURATED_FALLBACK: ReelItem[] = [
  {
    id: 'curated-a',
    kind: 'curated',
    src: '/videos/curated-a.mp4',
    duration_sec: 10,
    title: 'Curated A — BBB Loop',
  },
  {
    id: 'curated-b',
    kind: 'curated',
    src: '/videos/curated-b.mp4',
    duration_sec: 10,
    title: 'Curated B — Loop',
  },
  {
    id: 'curated-c',
    kind: 'curated',
    src: '/videos/curated-c.mp4',
    duration_sec: 10,
    title: 'Curated C — Loop',
  },
  // Remote fallbacks (used if local files fail to load)
  {
    id: 'curated-remote-bbb',
    kind: 'curated',
    src: 'https://www.w3schools.com/html/mov_bbb.mp4',
    duration_sec: 10,
    title: 'Remote BBB',
  },
];

/**
 * Optional local test videos generated via ffmpeg.
 * If ffmpeg was available at build time, these will exist under /videos/.
 * The player will try them first before falling back to remote URLs.
 */
export const LOCAL_CANDIDATES: string[] = [
  '/videos/curated-a.mp4',
  '/videos/curated-b.mp4',
  '/videos/curated-c.mp4',
];
