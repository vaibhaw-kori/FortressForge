/**
 * Display2 API client.
 * Fetches curated playlist and handles dynamic inserts.
 * No backend dependency required for standalone mode — falls back to local curated list.
 */
import { ReelItem } from '@aura/reel';
import { CURATED_FALLBACK } from './curated';

const API_BASE = '';

export async function fetchPlaylist(): Promise<ReelItem[]> {
  try {
    const res = await fetch(`${API_BASE}/api/reel/queue`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    // Backend returns ReelItemDTO[]; map to ReelItem
    if (Array.isArray(data)) {
      return data.map((d: any) => ({
        id: d.id,
        kind: d.kind ?? 'curated',
        src: d.src,
        duration_sec: d.duration_sec ?? 4,
        title: d.title ?? null,
      }));
    }
    if (Array.isArray((data as any).items)) {
      return (data as any).items.map((d: any) => ({
        id: d.id,
        kind: d.kind ?? 'curated',
        src: d.src,
        duration_sec: d.duration_sec ?? 4,
        title: d.title ?? null,
      }));
    }
  } catch (e) {
    console.warn('[stage] fetchPlaylist failed, using fallback', e);
  }
  return [...CURATED_FALLBACK];
}

export async function fetchReelPolicy(): Promise<Record<string, unknown> | null> {
  try {
    const res = await fetch(`${API_BASE}/api/reel/policy`);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}
