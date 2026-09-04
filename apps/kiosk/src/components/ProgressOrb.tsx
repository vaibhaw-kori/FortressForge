interface Props {
  progress: number; // 0..1
}

export function ProgressOrb({ progress }: Props) {
  const pct = Math.round(progress * 100);
  return (
    <div className="orb" aria-live="polite" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} role="progressbar">
      <div className="orb__ring" />
      <div className="orb__inner">{pct}%</div>
    </div>
  );
}