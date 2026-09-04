import { ExperienceDTO } from '@aura/contracts';

interface Props {
  experience: ExperienceDTO;
  active: boolean;
  onSelect: (e: ExperienceDTO) => void;
  /** Pre-localized duration label, e.g. "4 seconds". */
  durationLabel: string;
  /** Pre-localized call-to-action, e.g. "Select". */
  actionLabel: string;
}

export function ExperienceCard({ experience, active, onSelect, durationLabel, actionLabel }: Props) {
  const [primary, accent] = [
    experience.theme.palette.primary ?? '#7c5cff',
    experience.theme.palette.accent ?? '#00d4ff',
  ];
  return (
    <button
      type="button"
      className={`card ${active ? 'card--active' : ''}`}
      onClick={() => onSelect(experience)}
      aria-pressed={active}
    >
      <span
        className="card__aura"
        aria-hidden
        style={{
          background: `radial-gradient(circle, ${primary}55 0%, transparent 70%), radial-gradient(circle at 70% 70%, ${accent}55 0%, transparent 70%)`,
        }}
      />
      <h3 className="card__title">{experience.display_name}</h3>
      <p className="card__desc">{experience.description}</p>
      <div className="card__meta">
        <span className="card__chip">{durationLabel}</span>
        <span className="card__chip">{experience.visual_style.aesthetic}</span>
        <span className="card__action">{actionLabel} →</span>
      </div>
    </button>
  );
}
