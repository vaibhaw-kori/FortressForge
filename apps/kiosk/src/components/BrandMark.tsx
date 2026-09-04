import { ReactNode } from 'react';

export function BrandMark({ eyebrow, tagline }: { eyebrow: string; tagline?: ReactNode }) {
  return (
    <div className="brand">
      <div className="brand__mark" aria-hidden>
        A
      </div>
      <div className="brand__text">
        <div className="brand__eyebrow">{eyebrow}</div>
        {tagline ? <div className="brand__tagline">{tagline}</div> : null}
      </div>
    </div>
  );
}