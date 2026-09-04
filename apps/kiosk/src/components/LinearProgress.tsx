interface Props {
  progress: number; // 0..1
}

export function LinearProgress({ progress }: Props) {
  const pct = Math.max(0, Math.min(1, progress));
  return (
    <div className="linear" aria-valuenow={Math.round(pct * 100)} aria-valuemin={0} aria-valuemax={100} role="progressbar">
      <div className="linear__fill" style={{ width: `${pct * 100}%` }} />
    </div>
  );
}