import { useEffect, useState } from 'react';

interface Ready {
  status: string;
  db: { ok: boolean; error?: string };
}

interface ReelPolicy {
  policy: Record<string, unknown>;
}

export default function App() {
  const [ready, setReady] = useState<Ready | null>(null);
  const [reel, setReel] = useState<ReelPolicy | null>(null);

  useEffect(() => {
    fetch('/api/readyz').then((r) => r.json()).then(setReady).catch(() => {});
    fetch('/api/reel/policy').then((r) => r.json()).then(setReel).catch(() => {});
  }, []);

  return (
    <main className="console">
      <header className="console__header">
        <h1>AURA Operator</h1>
        <span className="console__pill">Live</span>
      </header>

      <section className="console__grid">
        <article className="card">
          <h3>Backend</h3>
          <p>Status: {ready?.status ?? '...'}</p>
          <p>DB: {ready?.db.ok ? 'ok' : 'down'}</p>
        </article>
        <article className="card">
          <h3>Reel Policy</h3>
          <pre className="card__code">
            {reel ? JSON.stringify(reel.policy, null, 2) : '...'}
          </pre>
        </article>
        <article className="card">
          <h3>Sessions</h3>
          <p>Operator console placeholder. Live events arrive via WS next.</p>
        </article>
      </section>
    </main>
  );
}