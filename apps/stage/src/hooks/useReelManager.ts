import { useEffect, useRef, useState, useCallback } from 'react';
import { ReelManager, ReelItem, ReelPolicyConfig, InsertPolicy } from '@aura/reel';

export function useReelManager(opts: { policy: ReelPolicyConfig; initialPlaylist: ReelItem[] }) {
  const managerRef = useRef<ReelManager | null>(null);
  if (!managerRef.current) {
    managerRef.current = new ReelManager({ policy: opts.policy, initialPlaylist: opts.initialPlaylist });
  }
  const manager = managerRef.current;

  const [current, setCurrent] = useState<ReelItem | null>(() => manager.getCurrent());
  const [playlist, setPlaylist] = useState<ReelItem[]>(() => manager.getPlaylist());
  const [version, setVersion] = useState(() => manager.getVersion());

  const sync = useCallback(() => {
    setCurrent(manager.getCurrent());
    setPlaylist(manager.getPlaylist());
    setVersion(manager.getVersion());
  }, [manager]);

  const enqueue = useCallback(
    (item: ReelItem, policy?: InsertPolicy) => {
      const res = manager.enqueue(item, policy);
      sync();
      return res;
    },
    [manager, sync],
  );

  const advance = useCallback(() => {
    const n = manager.advance();
    sync();
    return n;
  }, [manager, sync]);

  const jumpTo = useCallback(
    (id: string) => {
      const n = manager.jumpTo(id);
      sync();
      return n;
    },
    [manager, sync],
  );

  const handleError = useCallback(
    (id: string) => {
      const n = manager.handleError(id);
      sync();
      return n;
    },
    [manager, sync],
  );

  const setPolicy = useCallback(
    (p: ReelPolicyConfig) => {
      manager.setPolicy(p);
      sync();
    },
    [manager, sync],
  );

  const setPlaylistExternal = useCallback(
    (items: ReelItem[]) => {
      manager.setPlaylist(items);
      sync();
    },
    [manager, sync],
  );

  // Expose preload src
  const preloadSrc = manager.getPreloadSrc();

  return {
    manager,
    current,
    playlist,
    version,
    preloadSrc,
    enqueue,
    advance,
    jumpTo,
    handleError,
    setPolicy,
    setPlaylist: setPlaylistExternal,
    peekNext: () => manager.peekNext(),
  };
}
