interface Props {
  message: string;
  subtitle?: string;
  onDone: () => void;
  seconds?: number;
}

import { useEffect, useState } from 'react';

export function ResetCountdown({ message, subtitle, onDone, seconds = 8 }: Props) {
  const [n, setN] = useState(seconds);
  useEffect(() => {
    const id = window.setInterval(() => {
      setN((cur) => {
        if (cur <= 1) {
          window.clearInterval(id);
          onDone();
          return 0;
        }
        return cur - 1;
      });
    }, 1000);
    return () => window.clearInterval(id);
  }, [onDone]);

  return (
    <div className="screen" role="status" aria-live="polite">
      <p className="screen__eyebrow">AURA</p>
      <h2 className="screen__title">{message}</h2>
      {subtitle ? <p className="screen__sub muted">{subtitle}</p> : null}
      <div className="reset-countdown" aria-hidden>{n}</div>
    </div>
  );
}