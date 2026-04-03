"""
Content Engine — Image Generator
Generates background images for slides using Google Gemini (new google-genai SDK).
Multi-brand: uses shared API config.
"""

import os
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types

from src.brand import BrandConfig


class ImageGenerator:
    """Generates images using Google Gemini AI."""

    def __init__(self, brand_config: BrandConfig):
        self.config = brand_config.config
        self.img_config = self.config["image_generation"]

        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY environment variable not set")

        self.client = genai.Client(api_key=api_key)

    def generate_image(
        self,
        prompt: str,
        output_path: str,
        style: Optional[str] = None,
    ) -> str:
        """Generate a single image from prompt and save to file."""
        style = style or self.img_config.get("style", "photorealistic")
        width = self.img_config.get("width", 1080)
        height = self.img_config.get("height", 1920)

        full_prompt = (
            f"{prompt}. "
            f"Style: {style}, cinematic lighting, high quality, "
            f"vertical orientation {width}x{height}, "
            f"vibrant colors, professional photography look. "
            f"No text, no watermarks, no logos."
        )

        # Try Imagen 3 first, fall back to Gemini Flash
        try:
            return self._generate_with_imagen(full_prompt, output_path)
        except Exception as e:
            print(f"    ⚠️  Imagen failed ({e}), trying Gemini Flash...")
            try:
                return self._generate_with_gemini(full_prompt, output_path)
            except Exception as e2:
                print(f"    ⚠️  Gemini Flash failed ({e2}), using fallback gradient")
                return self._create_fallback_image(output_path)

    def _generate_with_imagen(self, prompt: str, output_path: str) -> str:
        """Generate image using Imagen 3 model."""
        response = self.client.models.generate_images(
            model="imagen-3.0-generate-001",
            prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                safety_filter_level="BLOCK_ONLY_HIGH",
                person_generation="DONT_ALLOW",
                aspect_ratio="9:16",
            ),
        )

        if response.generated_images:
            img_data = response.generated_images[0].image.image_bytes
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(img_data)
            return output_path
        raise RuntimeError("Imagen returned no images")

    def _generate_with_gemini(self, prompt: str, output_path: str) -> str:
        """Generate image using Gemini Flash with image output."""
        response = self.client.models.generate_content(
            model="gemini-2.5-flash-image",
            contents=f"Generate an image: {prompt}",
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"],
            ),
        )

        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.data:
                img_data = part.inline_data.data
                if isinstance(img_data, str):
                    import base64
                    img_data = base64.b64decode(img_data)

                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "wb") as f:
                    f.write(img_data)
                return output_path

        raise RuntimeError("Gemini returned no image data")

    def generate_slide_backgrounds(
        self,
        slides: list,
        output_dir: str,
    ) -> list[str]:
        """Generate background images for all slides in a scenario."""
        paths = []
        for slide in slides:
            filename = f"bg_slide_{slide.slide_number:02d}.png"
            output_path = str(Path(output_dir) / filename)
            try:
                path = self.generate_image(
                    prompt=slide.image_prompt,
                    output_path=output_path,
                )
                paths.append(path)
                print(f"  ✅ Slide {slide.slide_number} background generated")
            except Exception as e:
                print(f"  ❌ Slide {slide.slide_number} failed: {e}")
                path = self._create_fallback_image(output_path)
                paths.append(path)
        return paths

    def _create_fallback_image(self, output_path: str) -> str:
        """Create a gradient fallback image if generation fails."""
        from PIL import Image, ImageDraw

        width = self.img_config.get("width", 1080)
        height = self.img_config.get("height", 1920)

        img = Image.new("RGB", (width, height))
        draw = ImageDraw.Draw(img)

        for y in range(height):
            r = int(18 + (y / height) * 10)
            g = int(40 + (y / height) * 20)
            b = int(18 + (y / height) * 10)
            draw.line([(0, y), (width, y)], fill=(r, g, b))

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        img.save(output_path, "PNG")
        return output_path
