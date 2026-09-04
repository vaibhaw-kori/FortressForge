/**
 * ReelManager — framework-free playlist engine for Display 2.
 *
 * Responsibilities:
 * - Own the ordered playlist (curated + generated)
 * - Apply a configurable insertion policy without interrupting playback
 * - Expose continuous looping with optional play-once semantics
 * - Surface helpers for preloading and error recovery
 *
 * Policies:
 * - 'immediate' — interrupt and play next (no queue)
 * - 'queued'    — append to tail
 * - 'priority'  — insert immediately after current (position 1)
 * - 'play-once' — like priority, but auto-remove after one play
 *
 * The manager is pure: no DOM, no timers, no WS. The React hook owns side-effects.
 */

export type InsertPolicy = 'immediate' | 'queued' | 'priority' | 'play-once';

export interface ReelItem {
  id: string;
  kind: 'curated' | 'generated';
  src: string;
  duration_sec: number;
  title?: string | null;
  poster?: string | null;
  theme_id?: string | null;
  created_at?: number;
}

export interface ReelPolicyConfig {
  /** Default insertion policy applied when `handleNewVideo` is called without an explicit policy. */
  defaultInsert: InsertPolicy;
  /** Max generated items in queue before rejecting new ones (0 = unlimited). */
  maxGeneratedInQueue?: number;
  /** Minimum gap between generated inserts (seconds). Prototype: informational only. */
  minGapBetweenGeneratedSeconds?: number;
}

export interface ReelManagerOptions {
  policy: ReelPolicyConfig;
  initialPlaylist?: ReelItem[];
  /** Index to start at. Defaults to 0. */
  startIndex?: number;
}

export class ReelManager {
  private playlist: ReelItem[] = [];
  private currentIndex: number = 0;
  private playOnceIds: Set<string> = new Set();
  private policy: ReelPolicyConfig;
  /** Monotonic counter for queue ordering; not exposed. */
  private _version: number = 0;

  constructor(opts: ReelManagerOptions) {
    this.policy = { ...opts.policy };
    this.playlist = [...(opts.initialPlaylist ?? [])];
    this.currentIndex = opts.startIndex ?? 0;
    if (this.playlist.length > 0) {
      this.currentIndex = Math.max(0, Math.min(this.currentIndex, this.playlist.length - 1));
    } else {
      this.currentIndex = 0;
    }
  }

  // ---- getters ----

  getPlaylist(): ReelItem[] {
    return [...this.playlist];
  }

  getCurrent(): ReelItem | null {
    if (this.playlist.length === 0) return null;
    return this.playlist[this.currentIndex] ?? null;
  }

  /** Peek the item that would play after current, respecting looping and play-once. */
  peekNext(): ReelItem | null {
    if (this.playlist.length === 0) return null;
    if (this.playlist.length === 1) return this.playlist[0] ?? null;
    const next = (this.currentIndex + 1) % this.playlist.length;
    return this.playlist[next] ?? null;
  }

  getVersion(): number {
    return this._version;
  }

  getPolicy(): ReelPolicyConfig {
    return { ...this.policy };
  }

  setPolicy(policy: ReelPolicyConfig): void {
    this.policy = { ...policy };
    this._version++;
  }

  // ---- playlist mutation ----

  setPlaylist(items: ReelItem[]): void {
    const currentId = this.getCurrent()?.id;
    this.playlist = [...items];
    this.playOnceIds.clear();
    // Try to preserve current position by id, else reset to 0.
    if (currentId) {
      const idx = this.playlist.findIndex((i) => i.id === currentId);
      this.currentIndex = idx >= 0 ? idx : 0;
    } else {
      this.currentIndex = 0;
    }
    this._version++;
  }

  /**
   * Enqueue an item according to `policy` (or default).
   * Returns { accepted, reason, shouldInterrupt }.
   */
  enqueue(
    item: ReelItem,
    policy?: InsertPolicy,
  ): { accepted: boolean; reason: string; shouldInterrupt: boolean } {
    const p = policy ?? this.policy.defaultInsert;

    // Guard: duplicate id
    if (this.playlist.some((i) => i.id === item.id)) {
      return { accepted: false, reason: 'duplicate', shouldInterrupt: false };
    }

    // Guard: maxGeneratedInQueue
    if (this.policy.maxGeneratedInQueue && this.policy.maxGeneratedInQueue > 0) {
      const genCount = this.playlist.filter((i) => i.kind === 'generated').length;
      if (item.kind === 'generated' && genCount >= this.policy.maxGeneratedInQueue) {
        return { accepted: false, reason: 'queue_full', shouldInterrupt: false };
      }
    }

    if (p === 'immediate') {
      // Insert right after current and signal interruption.
      const insertAt = this.playlist.length === 0 ? 0 : this.currentIndex + 1;
      this.playlist.splice(insertAt, 0, item);
      this._version++;
      return { accepted: true, reason: 'immediate', shouldInterrupt: true };
    }

    if (p === 'priority' || p === 'play-once') {
      const insertAt = this.playlist.length === 0 ? 0 : this.currentIndex + 1;
      this.playlist.splice(insertAt, 0, item);
      if (p === 'play-once') this.playOnceIds.add(item.id);
      this._version++;
      return { accepted: true, reason: p, shouldInterrupt: false };
    }

    // queued (default)
    this.playlist.push(item);
    this._version++;
    return { accepted: true, reason: 'queued', shouldInterrupt: false };
  }

  /** Convenience wrapper for WebSocket handler: apply default policy. */
  handleNewVideo(item: ReelItem, policy?: InsertPolicy): { accepted: boolean; reason: string; shouldInterrupt: boolean } {
    return this.enqueue(item, policy);
  }

  remove(id: string): boolean {
    const idx = this.playlist.findIndex((i) => i.id === id);
    if (idx === -1) return false;
    this.playlist.splice(idx, 1);
    this.playOnceIds.delete(id);
    // Adjust currentIndex if needed
    if (this.playlist.length === 0) {
      this.currentIndex = 0;
    } else if (idx < this.currentIndex) {
      this.currentIndex--;
    } else if (idx === this.currentIndex) {
      // Removed current; stay at same index (now next item), wrap if needed
      if (this.currentIndex >= this.playlist.length) this.currentIndex = 0;
    }
    this._version++;
    return true;
  }

  /** Advance to next item, handling play-once removal and looping. */
  advance(): ReelItem | null {
    if (this.playlist.length === 0) return null;

    const current = this.getCurrent();
    // If current was play-once, remove it before advancing.
    let nextIndex: number;
    if (current && this.playOnceIds.has(current.id)) {
      const idx = this.playlist.findIndex((i) => i.id === current.id);
      if (idx !== -1) {
        this.playlist.splice(idx, 1);
        this.playOnceIds.delete(current.id);
        if (this.playlist.length === 0) {
          this.currentIndex = 0;
          this._version++;
          return null;
        }
        // Next is at same index (elements shifted), or wrap
        nextIndex = idx >= this.playlist.length ? 0 : idx;
        this.currentIndex = nextIndex;
        this._version++;
        return this.getCurrent();
      }
    }

    nextIndex = (this.currentIndex + 1) % this.playlist.length;
    this.currentIndex = nextIndex;
    return this.getCurrent();
  }

  jumpTo(id: string): ReelItem | null {
    const idx = this.playlist.findIndex((i) => i.id === id);
    if (idx === -1) return null;
    this.currentIndex = idx;
    return this.getCurrent();
  }

  /** Called on playback error: remove faulty item and advance. */
  handleError(id: string): ReelItem | null {
    const faultyIdx = this.playlist.findIndex((i) => i.id === id);
    if (faultyIdx === -1) return this.getCurrent();
    const wasCurrent = faultyIdx === this.currentIndex;
    this.remove(id);
    if (!wasCurrent) return this.getCurrent();
    // Was current: after removal, currentIndex already points at next
    return this.getCurrent();
  }

  /** Preload hint: src of the item after current. */
  getPreloadSrc(): string | null {
    const n = this.peekNext();
    return n ? n.src : null;
  }

  size(): number {
    return this.playlist.length;
  }

  isEmpty(): boolean {
    return this.playlist.length === 0;
  }
}