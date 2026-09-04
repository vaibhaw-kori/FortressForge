import { ReactNode } from 'react';

interface Props {
  title: ReactNode;
  message: ReactNode;
  retry?: ReactNode;
  reset?: ReactNode;
}

/**
 * Guest-facing error card. Only localized title/message are rendered —
 * technical codes are never shown to visitors.
 */
export function ErrorPanel({ title, message, retry, reset }: Props) {
  return (
    <div className="error-panel" role="alert">
      <div className="error-panel__title">{title}</div>
      <div className="error-panel__message">{message}</div>
      <div className="row" style={{ marginTop: 22, justifyContent: 'center' }}>
        {retry}
        {reset}
      </div>
    </div>
  );
}
