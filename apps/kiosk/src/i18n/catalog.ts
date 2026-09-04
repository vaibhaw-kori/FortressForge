/**
 * i18n catalog. Two languages for the prototype (English + Arabic).
 *
 * Adding a language:
 *   1. Add a new top-level key (e.g., 'fr').
 *   2. Translate every `KioskKey` value.
 *   3. No UI changes needed — language selection picks the catalog.
 *
 * Keys are namespaced by screen for clarity.
 */

export type KioskKey =
  | 'brand.eyebrow'
  | 'brand.tagline'
  | 'idle.invite'
  | 'idle.touch'
  | 'language.title'
  | 'language.subtitle'
  | 'language.option.en'
  | 'language.option.ar'
  | 'experience.title'
  | 'experience.subtitle'
  | 'experience.choose'
  | 'experience.back'
  | 'experience.duration'
  | 'experience.seconds'
  | 'ready.title'
  | 'ready.subtitle'
  | 'ready.capture'
  | 'ready.changeTheme'
  | 'ready.preview'
  | 'ready.noCamera'
  | 'countdown.hold'
  | 'countdown.cancel'
  | 'captured.review'
  | 'captured.title'
  | 'captured.retake'
  | 'captured.continue'
  | 'uploading.title'
  | 'uploading.subtitle'
  | 'generating.title'
  | 'generating.subtitle'
  | 'generating.preparing'
  | 'generating.animating'
  | 'generating.encoding'
  | 'generating.queued'
  | 'generating.processing'
  | 'generating.completed'
  | 'completed.title'
  | 'completed.subtitle'
  | 'completed.outputSoon'
  | 'completed.newSession'
  | 'reset.title'
  | 'reset.subtitle'
  | 'reset.countdown'
  | 'error.title'
  | 'error.subtitle'
  | 'error.retry'
  | 'error.reset'
  | 'error.unknown'
  | 'error.cameraDenied'
  | 'error.uploadFailed'
  | 'error.network';

export const en: Record<KioskKey, string> = {
  'brand.eyebrow': 'AURA',
  'brand.tagline': 'Become the artwork.',
  'idle.invite': 'Step closer to begin.',
  'idle.touch': 'Tap anywhere to start',
  'language.title': 'Choose your language',
  'language.subtitle': 'اللغة / Language',
  'language.option.en': 'English',
  'language.option.ar': 'العربية',
  'experience.title': 'Choose an experience',
  'experience.subtitle': 'Each one turns your portrait into a short film.',
  'experience.choose': 'Select',
  'experience.back': 'Change language',
  'experience.duration': '{n} seconds',
  'experience.seconds': 'sec',
  'ready.title': 'Ready when you are',
  'ready.subtitle': 'Look straight at the camera. Hold still.',
  'ready.capture': 'Capture',
  'ready.changeTheme': 'Change experience',
  'ready.preview': 'Live preview',
  'ready.noCamera': 'Camera unavailable',
  'countdown.hold': 'Hold still…',
  'countdown.cancel': 'Cancel',
  'captured.review': 'Reviewing your capture',
  'captured.title': 'Look good?',
  'captured.retake': 'Retake',
  'captured.continue': 'Continue',
  'uploading.title': 'Uploading',
  'uploading.subtitle': 'Sending your portrait to the studio…',
  'generating.title': 'Creating your film',
  'generating.subtitle': 'This usually takes 20–60 seconds.',
  'generating.preparing': 'Preparing studio…',
  'generating.queued': 'In queue…',
  'generating.processing': 'Processing…',
  'generating.animating': 'Animating your portrait…',
  'generating.encoding': 'Encoding final video…',
  'generating.completed': 'Almost ready',
  'completed.title': 'Your film is ready',
  'completed.subtitle': 'Look at the main display to watch it play.',
  'completed.outputSoon': 'It will appear on the big screen in a moment.',
  'completed.newSession': 'New visitor',
  'reset.title': 'Thank you',
  'reset.subtitle': 'Resetting for the next visitor.',
  'reset.countdown': 'Starting in {n}',
  'error.title': 'Something went wrong',
  'error.subtitle': 'We could not complete this session.',
  'error.retry': 'Try again',
  'error.reset': 'Start over',
  'error.unknown': 'Unexpected error',
  'error.cameraDenied': 'Camera access was blocked.',
  'error.uploadFailed': 'Upload failed.',
  'error.network': 'Network error.',
};

export const ar: Record<KioskKey, string> = {
  'brand.eyebrow': 'أورا',
  'brand.tagline': 'كن أنت اللوحة الفنية.',
  'idle.invite': 'اقترب للبدء.',
  'idle.touch': 'انقر في أي مكان للبدء',
  'language.title': 'اختر لغتك',
  'language.subtitle': 'Language / اللغة',
  'language.option.en': 'English',
  'language.option.ar': 'العربية',
  'experience.title': 'اختر التجربة',
  'experience.subtitle': 'كل تجربة تحوّل صورتك إلى فيلم قصير.',
  'experience.choose': 'اختيار',
  'experience.back': 'تغيير اللغة',
  'experience.duration': '{n} ثانية',
  'experience.seconds': 'ث',
  'ready.title': 'جاهز؟',
  'ready.subtitle': 'انظر مباشرةً إلى الكاميرا وحافظ على ثباتك.',
  'ready.capture': 'التقاط',
  'ready.changeTheme': 'تغيير التجربة',
  'ready.preview': 'معاينة مباشرة',
  'ready.noCamera': 'الكاميرا غير متاحة',
  'countdown.hold': 'حافظ على ثباتك…',
  'countdown.cancel': 'إلغاء',
  'captured.review': 'مراجعة الصورة',
  'captured.title': 'هل تبدو جيدة؟',
  'captured.retake': 'إعادة الالتقاط',
  'captured.continue': 'متابعة',
  'uploading.title': 'جاري الرفع',
  'uploading.subtitle': 'نرسل صورتك إلى الاستوديو…',
  'generating.title': 'نصنع فيلمك',
  'generating.subtitle': 'عادةً يستغرق ذلك ٢٠–٦٠ ثانية.',
  'generating.preparing': 'تجهيز الاستوديو…',
  'generating.queued': 'في قائمة الانتظار…',
  'generating.processing': 'قيد المعالجة…',
  'generating.animating': 'نحرّك صورتك…',
  'generating.encoding': 'ترميز الفيديو النهائي…',
  'generating.completed': 'جاهز تقريبًا',
  'completed.title': 'فيلمك جاهز',
  'completed.subtitle': 'شاهد الفيلم على الشاشة الرئيسية.',
  'completed.outputSoon': 'سيظهر على الشاشة الكبيرة بعد لحظات.',
  'completed.newSession': 'زائر جديد',
  'reset.title': 'شكرًا لك',
  'reset.subtitle': 'نُعيد التجهيز للزائر التالي.',
  'reset.countdown': 'يبدأ خلال {n}',
  'error.title': 'حدث خطأ ما',
  'error.subtitle': 'لم نتمكن من إكمال هذه الجلسة.',
  'error.retry': 'إعادة المحاولة',
  'error.reset': 'البدء من جديد',
  'error.unknown': 'خطأ غير متوقع',
  'error.cameraDenied': 'تم رفض الوصول إلى الكاميرا.',
  'error.uploadFailed': 'فشل الرفع.',
  'error.network': 'خطأ في الشبكة.',
};

export const CATALOGS: Record<string, Record<KioskKey, string>> = { en, ar };

export const RTL_LANGUAGES: ReadonlySet<string> = new Set(['ar']);

export function directionFor(language: string): 'ltr' | 'rtl' {
  return RTL_LANGUAGES.has(language) ? 'rtl' : 'ltr';
}

export function isSupportedLanguage(code: string): boolean {
  return code in CATALOGS;
}

export const SUPPORTED_LANGUAGES: ReadonlyArray<{ code: string; labelKey: KioskKey }> = [
  { code: 'en', labelKey: 'language.option.en' },
  { code: 'ar', labelKey: 'language.option.ar' },
];