"""
Content Engine — Scenario Generator
Generates viral TikTok/Shorts scripts using Gemini AI.
Supports multi-brand: each brand has its own system prompt, pillars, and style.
"""

import json
import random
import os
from pathlib import Path
from typing import Optional

import google.generativeai as genai
from pydantic import BaseModel

from src.brand import BrandConfig


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
    brand_id: str               # Which brand this belongs to
    title: str
    pillar: str
    hook: str
    slides: list[Slide]
    hashtags: list[str]
    description: str
    thumbnail_prompt: str
    cta: str


# ─── Prompt Template ──────────────────────────────────────────────

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
          "image_prompt": "English prompt for AI image generation. Photorealistic, 9:16 vertical, related to the slide topic."
        }}
      ],
      "hashtags": ["#hashtag1", "#hashtag2", ...],
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

    def __init__(self, brand_config: BrandConfig):
        self.bc = brand_config
        self.config = brand_config.config

        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY environment variable not set")

        genai.configure(api_key=api_key)
        model_name = self.config["scenario"]["model"]

        # Use brand-specific system prompt
        system_prompt = self.bc.system_prompt
        if not system_prompt:
            raise ValueError(f"No system_prompt defined for brand '{self.bc.brand_id}'")

        self.model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=system_prompt,
        )
        self.pillars = self.bc.pillars
        self.slides_count = self.config["scenario"].get("slides_count", 5)

    def _pick_pillar(self, pillar_id: Optional[str] = None) -> dict:
        """Pick a content pillar (weighted random or specific)."""
        if pillar_id:
            for p in self.pillars:
                if p["id"] == pillar_id:
                    return p
            raise ValueError(
                f"Unknown pillar '{pillar_id}' for brand '{self.bc.brand_id}'. "
                f"Available: {', '.join(self.bc.pillar_ids)}"
            )

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

        brand_prefix = self.bc.brand_id[:3]
        for i, item in enumerate(raw.get("scenarios", [raw] if "title" in raw else [])):
            scenario_id = f"{brand_prefix}_{pillar['id']}_{random.randint(1000, 9999)}"
            slides = [
                Slide(
                    slide_number=s["slide_number"],
                    text_on_screen=s["text_on_screen"],
                    tts_script=s["tts_script"],
                    image_prompt=s["image_prompt"],
                )
                for s in item["slides"]
            ]

            # Merge brand default tags with scenario hashtags
            default_tags = (
                self.config.get("upload", {})
                .get("youtube", {})
                .get("default_tags", [])
            )
            hashtags = item.get("hashtags", [])
            # Add brand hashtag if not present
            brand_tag = f"#{self.bc.brand_name.replace(' ', '')}"
            if brand_tag not in hashtags:
                hashtags.append(brand_tag)

            scenarios.append(Scenario(
                id=scenario_id,
                brand_id=self.bc.brand_id,
                title=item["title"],
                pillar=item.get("pillar", pillar["id"]),
                hook=item["hook"],
                slides=slides,
                hashtags=hashtags,
                description=item.get("description", ""),
                thumbnail_prompt=item.get("thumbnail_prompt", ""),
                cta=item.get("cta", f"Деталі на {self.bc.domain}"),
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


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    bc = BrandConfig()
    gen = ScenarioGenerator(bc)
    scenarios = gen.generate(count=1)
    for s in scenarios:
        print(f"\n{'='*60}")
        print(f"🏷️  Brand: {s.brand_id}")
        print(f"📹 {s.title}")
        print(f"🎯 Pillar: {s.pillar}")
        print(f"🪝 Hook: {s.hook}")
        for slide in s.slides:
            print(f"  [{slide.slide_number}] {slide.text_on_screen}")
            print(f"      🗣️ {slide.tts_script}")
        print(f"#️⃣ {' '.join(s.hashtags)}")
        path = gen.save_scenario(s)
        print(f"💾 Saved to: {path}")
