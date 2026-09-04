interface Props {
  language: string;
}

export function LanguagePill({ language }: Props) {
  const label = language === 'ar' ? 'AR' : 'EN';
  return (
    <div className="lang-pill" aria-label="language">
      <span className="lang-pill__dot" />
      {label}
    </div>
  );
}