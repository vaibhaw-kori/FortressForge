/**
 * Countdown timer hook. Calls onTick each second, onComplete at zero.
 * Pause/resume via `running`. Cancel resets remaining to the configured total.
 */
import { useEffect, useRef } from 'react';

export interface UseCountdownOptions {
  total: number;
  running: boolean;
  onTick: (remaining: number) => void;
  onComplete: () => void;
}

export function useCountdown({ total, running, onTick, onComplete }: UseCountdownOptions): void {
  const tickRef = useRef(onTick);
  const doneRef = useRef(onComplete);
  tickRef.current = onTick;
  doneRef.current = onComplete;

  useEffect(() => {
    if (!running) return;
    let remaining = total;
    tickRef.current(remaining);
    const id = window.setInterval(() => {
      remaining -= 1;
      if (remaining <= 0) {
        window.clearInterval(id);
        doneRef.current();
        return;
      }
      tickRef.current(remaining);
    }, 1000);
    return () => window.clearInterval(id);
  }, [running, total]);
}