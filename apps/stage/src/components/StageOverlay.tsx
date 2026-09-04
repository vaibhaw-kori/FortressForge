import type { ReelItem, ReelPolicyConfig } from '@aura/reel';

interface Props {
  current: ReelItem | null;
  playlist: ReelItem[];
  policy: ReelPolicyConfig;
  onPolicyChange: (p: ReelPolicyConfig) => void;
  wsStatus: string;
  isFullscreen: boolean;
  onToggleFullscreen: () => void;
}

export function StageOverlay({ current, playlist, policy, onPolicyChange, wsStatus, isFullscreen, onToggleFullscreen }: Props) {
  return (
    <div className="stage-overlay">
      <div className="stage-overlay__top">
        <div className="brand">
          <div className="brand__mark">AURA</div>
          <div className="brand__meta">
            <div className="brand__title">Display 2 — Reel</div>
            <div className="brand__sub">
              {current ? `${current.title ?? current.id} • ${current.kind}` : 'Idle'} • WS: {wsStatus}
            </div>
          </div>
        </div>
        <div className="stage-overlay__actions">
          <select
            value={policy.defaultInsert}
            onChange={(e) => onPolicyChange({ ...policy, defaultInsert: e.target.value as ReelPolicyConfig['defaultInsert'] })}
            className="stage-select"
            aria-label="Insert policy"
          >
            <option value="queued">Queued</option>
            <option value="priority">Priority</option>
            <option value="immediate">Immediate</option>
            <option value="play-once">Play-once</option>
          </select>
          <button className="stage-btn" onClick={onToggleFullscreen}>
            {isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'}
          </button>
        </div>
      </div>

      <div className="stage-overlay__bottom">
        <div className="stage-playlist">
          {playlist.map((item) => (
            <span
              key={item.id}
              className={`stage-playlist__dot ${item.id === current?.id ? 'stage-playlist__dot--active' : ''} ${item.kind === 'generated' ? 'stage-playlist__dot--generated' : ''}`}
              title={`${item.title ?? item.id} (${item.kind})`}
            />
          ))}
          <span className="stage-playlist__count">{playlist.length} items</span>
        </div>
      </div>
    </div>
  );
}
