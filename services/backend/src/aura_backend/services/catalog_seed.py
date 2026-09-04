"""In-memory experience catalog seed for the prototype.

Production replaces this with an operator-managed catalog stored in
DB / object storage.

Each experience ships with:
- Trusted AI-generation config (prompt, negative_prompt, model params).
- Visual style + motion descriptors.
- Localized display name + description in EN + AR.
- Explicit display_order for the kiosk selector.

Crucially: the frontend never receives raw prompts or model params
directly; the backend resolves `experience_id` -> Experience and the
kiosk only renders the UI-facing fields (display_name, description,
thumbnail, palette). AI fields are reserved for the provider layer.
"""

from __future__ import annotations

from ..domain import (
    DEFAULT_LANGUAGE,
    Experience,
    ExperienceTheme,
    LocalizedText,
    ModelParams,
    MotionConfig,
    VisualStyle,
)

SEED_EXPERIENCES: list[Experience] = [
    Experience(
        id="aurora",
        display_name="Aurora",
        description="Flowing neon ribbons drifting through an arctic sky.",
        duration_sec=4.0,
        fps=12,
        resolution="720x1280",
        aspect_ratio="9:16",
        thumbnail_url=None,
        enabled=True,
        display_order=10,
        prompt=(
            "Cinematic portrait of the visitor surrounded by flowing neon aurora ribbons. "
            "Arctic sky background, soft volumetric light, ethereal particles, "
            "gentle camera dolly-in motion. High production value, 35mm film look."
        ),
        negative_prompt=(
            "blurry, low quality, deformed face, extra limbs, watermark, text, "
            "frame artifacts, harsh shadows"
        ),
        visual_style=VisualStyle(
            aesthetic="cinematic",
            palette_name="aurora",
            keywords=("aurora", "neon", "ribbons", "ethereal", "arctic"),
            lighting="soft",
            texture="smooth",
        ),
        motion=MotionConfig(
            strength=0.7,
            camera_motion="dolly",
            easing="ease_in_out",
            intensity=0.55,
            loop=False,
        ),
        model_params=ModelParams(
            num_inference_steps=28,
            guidance_scale=7.5,
            motion_bucket_id=180,
            seed_policy="random",
            fixed_seed=None,
            strength=0.65,
            extra={"identity_weight": 0.85, "style_weight": 0.6},
        ),
        theme=ExperienceTheme(
            palette={"primary": "#7c5cff", "accent": "#00d4ff", "bg": "#050608"},
            background_music=None,
        ),
        metadata={"category": "abstract", "difficulty": "easy"},
        localized_names=LocalizedText(
            translations={"en": "Aurora", "ar": "الشفق القطبي"},
            rtl=True,
        ),
        localized_descriptions=LocalizedText(
            translations={
                "en": "Flowing neon ribbons drifting through an arctic sky.",
                "ar": "أشرطة نيون متدفقة تنساب عبر سماء قطبية.",
            },
            rtl=True,
        ),
        supported_languages=("en", "ar"),
        default_language=DEFAULT_LANGUAGE,
        rtl_text=True,
    ),
    Experience(
        id="mirage",
        display_name="Mirage",
        description="A shimmering desert oasis with golden particles.",
        duration_sec=5.0,
        fps=12,
        resolution="720x1280",
        aspect_ratio="9:16",
        thumbnail_url=None,
        enabled=True,
        display_order=20,
        prompt=(
            "Cinematic portrait of the visitor beside a shimmering desert oasis at golden hour. "
            "Heat haze, golden dust particles suspended in warm light, "
            "subtle camera orbit. Luxury perfume-ad aesthetic, soft bokeh."
        ),
        negative_prompt=(
            "blurry, low quality, deformed face, extra limbs, watermark, text, "
            "harsh midday sun, oversaturated"
        ),
        visual_style=VisualStyle(
            aesthetic="environment",
            palette_name="mirage",
            keywords=("desert", "oasis", "gold", "particles", "heat"),
            lighting="dramatic",
            texture="grain",
        ),
        motion=MotionConfig(
            strength=0.6,
            camera_motion="orbit",
            easing="ease_in_out",
            intensity=0.5,
            loop=False,
        ),
        model_params=ModelParams(
            num_inference_steps=30,
            guidance_scale=7.0,
            motion_bucket_id=160,
            seed_policy="random",
            fixed_seed=None,
            strength=0.6,
            extra={"identity_weight": 0.8, "style_weight": 0.7},
        ),
        theme=ExperienceTheme(
            palette={"primary": "#ffb547", "accent": "#ffe7a3", "bg": "#1a0f00"},
            background_music=None,
        ),
        metadata={"category": "environment", "difficulty": "easy"},
        localized_names=LocalizedText(
            translations={"en": "Mirage", "ar": "سراب"},
            rtl=True,
        ),
        localized_descriptions=LocalizedText(
            translations={
                "en": "A shimmering desert oasis with golden particles.",
                "ar": "واحة صحراويه متلألئه مع ذر ذهبيه.",
            },
            rtl=True,
        ),
        supported_languages=("en", "ar"),
        default_language=DEFAULT_LANGUAGE,
        rtl_text=True,
    ),
    Experience(
        id="pulse",
        display_name="Pulse",
        description="High-contrast geometric waves synced to a beat.",
        duration_sec=3.0,
        fps=24,
        resolution="720x1280",
        aspect_ratio="9:16",
        thumbnail_url=None,
        enabled=True,
        display_order=30,
        prompt=(
            "Bold kinetic portrait of the visitor with high-contrast geometric waves. "
            "Magenta and white color blocks, sharp motion synced to a beat, "
            "fast parallax camera move. Music video aesthetic."
        ),
        negative_prompt=(
            "blurry, low quality, deformed face, extra limbs, watermark, text, "
            "soft lighting, muted colors"
        ),
        visual_style=VisualStyle(
            aesthetic="kinetic",
            palette_name="pulse",
            keywords=("kinetic", "geometric", "wave", "beat", "neon"),
            lighting="high_key",
            texture="smooth",
        ),
        motion=MotionConfig(
            strength=0.85,
            camera_motion="parallax",
            easing="ease_out",
            intensity=0.8,
            loop=True,
        ),
        model_params=ModelParams(
            num_inference_steps=22,
            guidance_scale=8.0,
            motion_bucket_id=220,
            seed_policy="random",
            fixed_seed=None,
            strength=0.75,
            extra={"identity_weight": 0.75, "style_weight": 0.85},
        ),
        theme=ExperienceTheme(
            palette={"primary": "#ff3b8b", "accent": "#ffffff", "bg": "#0b0d12"},
            background_music=None,
        ),
        metadata={"category": "kinetic", "difficulty": "easy"},
        localized_names=LocalizedText(
            translations={"en": "Pulse", "ar": "نبض"},
            rtl=True,
        ),
        localized_descriptions=LocalizedText(
            translations={
                "en": "High-contrast geometric waves synced to a beat.",
                "ar": "موجات هندسيه عاليه التباين متناغمه مع الإيقاع.",
            },
            rtl=True,
        ),
        supported_languages=("en", "ar"),
        default_language=DEFAULT_LANGUAGE,
        rtl_text=True,
    ),
    Experience(
        id="driftwood",
        display_name="Driftwood",
        description="Calm cinematic drift along a moonlit shoreline.",
        duration_sec=6.0,
        fps=12,
        resolution="720x1280",
        aspect_ratio="9:16",
        thumbnail_url=None,
        enabled=False,  # disabled for testing enabled-only filter
        display_order=40,
        prompt=(
            "Quiet cinematic portrait of the visitor on a moonlit shoreline. "
            "Long exposure water, soft moonlight, gentle drift. "
            "Contemplative, painterly, slow camera dolly."
        ),
        negative_prompt=(
            "blurry, low quality, deformed face, extra limbs, watermark, text, "
            "overexposed, garish colors"
        ),
        visual_style=VisualStyle(
            aesthetic="cinematic",
            palette_name="driftwood",
            keywords=("moonlit", "shore", "calm", "painterly", "drift"),
            lighting="low_key",
            texture="paper",
        ),
        motion=MotionConfig(
            strength=0.4,
            camera_motion="dolly",
            easing="ease_in_out",
            intensity=0.3,
            loop=False,
        ),
        model_params=ModelParams(
            num_inference_steps=35,
            guidance_scale=6.5,
            motion_bucket_id=120,
            seed_policy="fixed",
            fixed_seed=4242,
            strength=0.5,
            extra={"identity_weight": 0.85, "style_weight": 0.5},
        ),
        theme=ExperienceTheme(
            palette={"primary": "#5e8aa6", "accent": "#cfd9e2", "bg": "#0c1116"},
            background_music=None,
        ),
        metadata={"category": "cinematic", "difficulty": "advanced"},
        localized_names=LocalizedText(
            translations={"en": "Driftwood", "ar": "خشب منساب"},
            rtl=True,
        ),
        localized_descriptions=LocalizedText(
            translations={
                "en": "Calm cinematic drift along a moonlit shoreline.",
                "ar": "انجراف سينمائي هادئ على شاطئ تحت ضوء القمر.",
            },
            rtl=True,
        ),
        supported_languages=("en", "ar"),
        default_language=DEFAULT_LANGUAGE,
        rtl_text=True,
    ),
]