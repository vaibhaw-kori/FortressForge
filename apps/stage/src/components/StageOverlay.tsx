import type { ReelItem } from '@aura/reel';

interface Props {
  current: ReelItem | null;
  playlist: ReelItem[];
  /** When true the chrome fades out so the film plays edge-to-edge. */
  hidden?: boolean;
}

/**
 * Minimal presentation chrome for the installation wall.
 * No controls, no status text, no counts: a quiet brand mark plus
 * progress dots. The parent auto-hides it during playback.
 */
export function StageOverlay({ current, playlist, hidden = false }: Props) {
  return (
    <div className={`stage-overlay${hidden ? ' stage-overlay--hidden' : ''}`} aria-hidden>
      <div className="stage-overlay__top">
        <div className="brand">
          <div className="brand__mark">A</div>
        </div>
      </div>

      <div className="stage-overlay__bottom">
        <div className="stage-playlist">
          {playlist.map((item) => (
            <span
              key={item.id}
              className={`stage-playlist__dot${item.id === current?.id ? ' stage-playlist__dot--active' : ''}${item.kind === 'generated' ? ' stage-playlist__dot--generated' : ''}`}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
