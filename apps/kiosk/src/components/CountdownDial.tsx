import { useId } from 'react';

interface Props {
  total: number;
  remaining: number;
}

export function CountdownDial({ total, remaining }: Props) {
  const id = useId().replace(/:/g, '');
  const pct = total > 0 ? remaining / total : 0;
  const radius = 90;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - pct);
  return (
    <div className="countdown" aria-live="polite" aria-label={`${remaining} seconds remaining`}>
      <svg className="countdown__ring" viewBox="0 0 200 200" aria-hidden>
        <defs>
          <linearGradient id={`g-${id}`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#7c5cff" />
            <stop offset="100%" stopColor="#00d4ff" />
          </linearGradient>
        </defs>
        <circle className="countdown__bg" cx="100" cy="100" r={radius} />
        <circle
          className="countdown__fg"
          cx="100"
          cy="100"
          r={radius}
          stroke={`url(#g-${id})`}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
        />
      </svg>
      <div className="countdown__number">{remaining}</div>
    </div>
  );
}