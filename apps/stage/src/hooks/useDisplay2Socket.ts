import { useEffect, useRef, useState } from 'react';
import { createDisplay2Socket, Display2Incoming } from '../services/ws';

export function useDisplay2Socket(stageId: string, onEvent: (ev: Display2Incoming) => void) {
  const [status, setStatus] = useState<'connecting' | 'open' | 'closed' | 'error'>('connecting');
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    const handle: Display2Incoming & { job_id?: string } = null as any;
    void handle;
    const sock = createDisplay2Socket({
      stageId,
      onEvent: (ev) => onEventRef.current(ev),
      onStatusChange: setStatus,
    });
    return () => sock.close();
  }, [stageId]);

  return status;
}
