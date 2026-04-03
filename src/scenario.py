"""
Content Engine — Scenario Generator
Generates viral TikTok/Shorts scripts using Gemini AI (new google-genai SDK).
Supports multi-brand: each brand has its own system prompt, pillars, and style.
"""

import json
import random
import os
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types
from pydantic import BaseModel

from src.brand import BrandConfig


# ─── Data Models ───────────────────────────────────────────────────

class Slide(BaseModel):
    """Single slide in the video."""
    slide_number: int
    text_on_screen: str
    tts_script: str
    image_prompt: str
    duration_hint: float = 0.0


class Scenario(BaseModel):
    """Complete video scenario."""
    id: str
    brand_id: str
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

        self.client = genai.Client(api_key=api_key)
        self.model_name = self.config["scenario"]["model"]

        self.system_prompt = self.bc.system_prompt
        if not self.system_prompt:
            raise ValueError(f"No system_prompt defined for brand '{self.bc.brand_id}'")

        self.pillars = self.bc.pillars
        self.slides_count = self.config["scenario"].get("slides_count", 5)

    def _pick_pillar(self, pillar_id: Optional[str] = None) -> dict:
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
        prompt = self._pick_pillar(pillar_id)

        user_prompt = GENERATION_PROMPT.format(
            count=count,
            pillar_name=prompt["name"],
            pillar_description=prompt["description"],
            pillar_id=prompt["id"],
            slides_count=self.slides_count,
        )

        response = self.client.models.generate_content(
            model=self.model_name,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=self.system_prompt,
                response_mime_type="application/json",
                temperature=0.9,
                top_p=0.95,
            ),
        )

        # Parse JSON response (with cleanup for common Gemini quirks)
        text = response.text.strip()
        # Sometimes Gemini wraps JSON in markdown code blocks
        if text.startswith("```"):
            text = text.split("\n", 1)[1]  # Remove first line
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            # Try to fix common JSON issues and extract
            import re
            # Remove trailing commas before } or ]
            cleaned = re.sub(r',\s*([\]}])', r'\1', text)
            # Fix unescaped single quotes inside strings
            cleaned = cleaned.replace("'", "\u2019")
            try:
                raw = json.loads(cleaned)
            except json.JSONDecodeError:
                # Last resort: extract first JSON object
                match = re.search(r'\{[\s\S]*\}', cleaned)
                if match:
                    raw = json.loads(match.group())
                else:
                    raise ValueError(f"Could not parse Gemini response as JSON: {text[:300]}...")

        scenarios = []

        brand_prefix = self.bc.brand_id[:3]
        for i, item in enumerate(raw.get("scenarios", [raw] if "title" in raw else [])):
            scenario_id = f"{brand_prefix}_{prompt['id']}_{random.randint(1000, 9999)}"
            slides = [
                Slide(
                    slide_number=s["slide_number"],
                    text_on_screen=s["text_on_screen"],
                    tts_script=s["tts_script"],
                    image_prompt=s["image_prompt"],
                )
                for s in item["slides"]
            ]

            hashtags = item.get("hashtags", [])
            brand_tag = f"#{self.bc.brand_name.replace(' ', '')}"
            if brand_tag not in hashtags:
                hashtags.append(brand_tag)

            scenarios.append(Scenario(
                id=scenario_id,
                brand_id=self.bc.brand_id,
                title=item["title"],
                pillar=item.get("pillar", prompt["id"]),
                hook=item["hook"],
                slides=slides,
                hashtags=hashtags,
                description=item.get("description", ""),
                thumbnail_prompt=item.get("thumbnail_prompt", ""),
                cta=item.get("cta", f"Деталі на {self.bc.domain}"),
            ))

        return scenarios

    def save_scenario(self, scenario: Scenario, output_dir: str = "output") -> str:
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
