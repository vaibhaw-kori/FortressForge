/**
 * Reel playback primitives shared between Display 2 (stage) and operator UI.
 */

export * from './ReelManager';

export interface ReelPolicy {
  insertMode: 'fifo' | 'priority' | 'manual';
  maxGeneratedInQueue: number;
  minGapBetweenGeneratedSeconds: number;
  percentageOfReelForGenerated: number;
}

export interface ReelDecision {
  accept: boolean;
  reason: string;
  position: number;
}

import type { ReelItem } from './ReelManager';

export function decideInsert(
  queue: ReelItem[],
  newItem: ReelItem,
  policy: ReelPolicy,
  now: number = Date.now() / 1000,
): ReelDecision {
  const generated = queue.filter((i) => i.kind === 'generated');
  if (generated.length >= policy.maxGeneratedInQueue) {
    return { accept: false, reason: 'queue_full', position: -1 };
  }
  const last = generated[generated.length - 1];
  if (last && now - (last as unknown as { created_at?: number }).created_at! < policy.minGapBetweenGeneratedSeconds) {
    return { accept: false, reason: 'min_gap', position: -1 };
  }
  const position = policy.insertMode === 'priority' ? 1 : -1;
  return { accept: true, reason: 'accepted', position };
}