"""
HomeDome Content Engine — Scenario Generator
Generates viral TikTok/Shorts scripts using Gemini AI.
Each scenario includes: hook, slides with text, TTS script, image prompts,
hashtags, and upload metadata.
"""

import json
import random
import yaml
import os
from pathlib import Path
from typing import Optional

import google.generativeai as genai
from pydantic import BaseModel


# ─── Data Models ───────────────────────────────────────────────────

class Slide(BaseModel):
    """Single slide in the video."""
    slide_number: int
    text_on_screen: str        # Short text overlay (max 15 words)
    tts_script: str             # What the voice says (can be longer)
    image_prompt: str           # Prompt for background image generation
    duration_hint: float = 0.0  # Will be set by TTS audio length


class Scenario(BaseModel):
    """Complete video scenario."""
    id: str
    title: str
    pillar: str                 # Content pillar (fear_hook, education, etc.)
    hook: str                   # First 3 seconds hook text
    slides: list[Slide]
    hashtags: list[str]
    description: str            # Video description for TikTok/YouTube
    thumbnail_prompt: str       # Prompt for thumbnail generation
    cta: str                    # Call to action


# ─── Prompt Templates ──────────────────────────────────────────────

SYSTEM_PROMPT = """Ти — топовий сценарист коротких відео для TikTok та YouTube Shorts.
Ти працюєш на бренд HomeDome (homedome.com.ua) — компанію, яка підбирає,
постачає та встановлює ІБП (безперебійники), сонячні станції та ESS-системи
(системи накопичення енергії) для домів, квартир та бізнесу в Україні.

ВАЖЛИВО — правила вірусного контенту:
1. ХУК (перші 1-2 секунди) — шокуюче питання, страшний факт, або провокація.
   Людина МУСИТЬ зупинити скрол. Приклади хуків:
   - "Твій ІБП вб'є тебе цієї зими ☠️"
   - "90% українців роблять ЦЮ помилку з генератором"
   - "Я заощадив 47,000 грн за рік. Ось як."
   - "Сонячні панелі — РОЗВОД? 🤔"
2. КОЖЕН слайд — коротко (до 12 слів на екрані), але TTS може бути довшим.
3. Структура: Хук → Проблема → Рішення → Доказ/Факт → CTA
4. CTA завжди веде на homedome.com.ua
5. Мова — УКРАЇНСЬКА, розмовна, жива, без канцелярщини.
6. Емоції > логіка. Страх відключення > технічні характеристики.
7. Використовуй числа та конкретику: "47,000 грн", "за 3 дні", "на 15 років".

Відповідай ТІЛЬКИ у форматі JSON."""

GENERATION_PROMPT = """Створи {count} сценаріїв для коротких відео (TikTok/YouTube Shorts).

Тематичний напрям для цього батчу: {pillar_name} — {pillar_description}

Для КОЖНОГО сценарію дай JSON з такою структурою:
{{
  "scenarios": [
    {{
      "title": "Назва відео (коротка, для внутрішнього використання)",
      "pillar": "{pillar_id}",
      "hook": "Текст хука — перші слова які бачить глядач",
      "slides": [
        {{
          "slide_number": 1,
          "text_on_screen": "Короткий текст НА СЛАЙДІ (до 12 слів, великі літери для акценту)",
          "tts_script": "Повний текст який читає диктор для цього слайду (може бути довшим)",
          "image_prompt": "English prompt for AI image generation. Photorealistic, 9:16 vertical, related to the slide topic. Energy/home theme."
        }}
      ],
      "hashtags": ["#ІБП", "#HomeDome", "#сонячніпанелі", ...],
      "description": "Опис для TikTok/YouTube (2-3 речення з CTA)",
      "thumbnail_prompt": "English prompt for eye-catching thumbnail image",
      "cta": "Текст заклику до дії"
    }}
  ]
}}

Кожен сценарій повинен мати {slides_count} слайдів.
Перший слайд — ЗАВЖДИ хук.
Останній слайд — ЗАВЖДИ CTA з branding.

Image prompts повинні бути англійською, фотореалістичні, вертикальні (9:16).
Уникай однакових промтів — кожне зображення має бути унікальним.
"""


# ─── Generator ─────────────────────────────────────────────────────

class ScenarioGenerator:
    """Generates video scenarios using Gemini AI."""

    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY environment variable not set")

        genai.configure(api_key=api_key)
        model_name = self.config["scenario"]["model"]
        self.model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=SYSTEM_PROMPT,
        )
        self.pillars = self.config["scenario"]["pillars"]
        self.slides_count = self.config["scenario"]["slides_count"]

    def _pick_pillar(self, pillar_id: Optional[str] = None) -> dict:
        """Pick a content pillar (weighted random or specific)."""
        if pillar_id:
            for p in self.pillars:
                if p["id"] == pillar_id:
                    return p
            raise ValueError(f"Unknown pillar: {pillar_id}")

        # Weighted random selection
        weights = [p["weight"] for p in self.pillars]
        return random.choices(self.pillars, weights=weights, k=1)[0]

    def generate(
        self,
        count: int = 1,
        pillar_id: Optional[str] = None,
    ) -> list[Scenario]:
        """Generate video scenarios."""
        pillar = self._pick_pillar(pillar_id)

        prompt = GENERATION_PROMPT.format(
            count=count,
            pillar_name=pillar["name"],
            pillar_description=pillar["description"],
            pillar_id=pillar["id"],
            slides_count=self.slides_count,
        )

        response = self.model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.9,
                top_p=0.95,
            ),
        )

        raw = json.loads(response.text)
        scenarios = []

        for i, item in enumerate(raw.get("scenarios", [raw] if "title" in raw else [])):
            scenario_id = f"hd_{pillar['id']}_{random.randint(1000, 9999)}"
            slides = [
                Slide(
                    slide_number=s["slide_number"],
                    text_on_screen=s["text_on_screen"],
                    tts_script=s["tts_script"],
                    image_prompt=s["image_prompt"],
                )
                for s in item["slides"]
            ]

            scenarios.append(Scenario(
                id=scenario_id,
                title=item["title"],
                pillar=item.get("pillar", pillar["id"]),
                hook=item["hook"],
                slides=slides,
                hashtags=item.get("hashtags", ["#HomeDome", "#ІБП"]),
                description=item.get("description", ""),
                thumbnail_prompt=item.get("thumbnail_prompt", ""),
                cta=item.get("cta", "Деталі на homedome.com.ua"),
            ))

        return scenarios

    def save_scenario(self, scenario: Scenario, output_dir: str = "output") -> str:
        """Save scenario to JSON file."""
        path = Path(output_dir) / scenario.id
        path.mkdir(parents=True, exist_ok=True)
        file_path = path / "scenario.json"
        file_path.write_text(
            scenario.model_dump_json(indent=2),
            encoding="utf-8",
        )
        return str(file_path)


# ─── CLI Entry ─────────────────────────────────────────────────────

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    gen = ScenarioGenerator()
    scenarios = gen.generate(count=1)
    for s in scenarios:
        print(f"\n{'='*60}")
        print(f"📹 {s.title}")
        print(f"🎯 Pillar: {s.pillar}")
        print(f"🪝 Hook: {s.hook}")
        for slide in s.slides:
            print(f"  [{slide.slide_number}] {slide.text_on_screen}")
            print(f"      🗣️ {slide.tts_script}")
        print(f"#️⃣ {' '.join(s.hashtags)}")
        path = gen.save_scenario(s)
        print(f"💾 Saved to: {path}")
