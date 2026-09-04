import { ReactNode } from 'react';

interface Props {
  code?: string;
  message: ReactNode;
  retry?: ReactNode;
  reset?: ReactNode;
}

export function ErrorPanel({ code, message, retry, reset }: Props) {
  return (
    <div className="error-panel" role="alert">
      {code ? <div className="error-panel__code">{code}</div> : null}
      <div style={{ fontSize: 20, lineHeight: 1.4 }}>{message}</div>
      <div className="row" style={{ marginTop: 22, justifyContent: 'center' }}>
        {retry}
        {reset}
      </div>
    </div>
  );
}