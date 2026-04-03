"""
Content Engine — Slide Renderer
Creates professional slides with text overlays on AI-generated backgrounds.
Multi-brand: uses brand colors, tagline, domain for branding elements.
"""

import os
import random
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from src.brand import BrandConfig


class SlideRenderer:
    """Renders text slides with professional design."""

    def __init__(self, brand_config: BrandConfig):
        self.config = brand_config.config
        self.brand = brand_config.brand
        self.video_config = self.config["video"]
        self.slide_config = self.config["slides"]
        self.width = self.video_config["width"]
        self.height = self.video_config["height"]
        self._setup_fonts()

    def _setup_fonts(self):
        """Setup fonts — tries bundled, then system, then default."""
        font_paths = [
            "fonts/Montserrat-Bold.ttf",
            "fonts/Montserrat-Regular.ttf",
            "fonts/Montserrat-Black.ttf",
        ]
        system_fonts = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "C:/Windows/Fonts/arial.ttf",
        ]

        self.font_bold_path = None
        self.font_regular_path = None

        for fp in font_paths:
            if os.path.exists(fp):
                if "Bold" in fp or "Black" in fp:
                    self.font_bold_path = fp
                else:
                    self.font_regular_path = fp

        if not self.font_bold_path:
            for fp in system_fonts:
                if os.path.exists(fp):
                    self.font_bold_path = fp
                    self.font_regular_path = fp
                    break

    def _get_font(self, size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
        path = self.font_bold_path if bold else (self.font_regular_path or self.font_bold_path)
        if path:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
        return ImageFont.load_default()

    def _hex_to_rgb(self, hex_color: str) -> tuple:
        hex_color = hex_color.lstrip("#")
        if len(hex_color) == 8:
            return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4, 6))
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

    def _create_gradient_overlay(self, width, height, opacity=0.65, style="vertical"):
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        if style == "vertical":
            for y in range(height):
                if y < height * 0.3:
                    alpha = int(255 * opacity * (1 - y / (height * 0.3)) * 0.7)
                elif y > height * 0.55:
                    progress = (y - height * 0.55) / (height * 0.45)
                    alpha = int(255 * opacity * progress)
                else:
                    alpha = int(255 * opacity * 0.3)
                draw.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
        elif style == "full":
            for y in range(height):
                draw.line([(0, y), (width, y)], fill=(0, 0, 0, int(255 * opacity)))

        return overlay

    def _draw_text_with_shadow(self, draw, position, text, font,
                                fill="#FFFFFF", shadow_color="#000000",
                                shadow_offset=3, anchor="la"):
        x, y = position
        rgb_shadow = self._hex_to_rgb(shadow_color)
        rgb_fill = self._hex_to_rgb(fill)

        for dx in range(-shadow_offset, shadow_offset + 1):
            for dy in range(-shadow_offset, shadow_offset + 1):
                if dx == 0 and dy == 0:
                    continue
                draw.text((x + dx, y + dy), text, font=font,
                          fill=(*rgb_shadow, 180), anchor=anchor)
        draw.text(position, text, font=font, fill=rgb_fill, anchor=anchor)

    def _wrap_text(self, text, font, max_width):
        words = text.split()
        lines = []
        current_line = ""

        for word in words:
            test_line = f"{current_line} {word}".strip()
            bbox = font.getbbox(test_line)
            if bbox[2] > max_width and current_line:
                lines.append(current_line)
                current_line = word
            else:
                current_line = test_line

        if current_line:
            lines.append(current_line)
        return lines

    def render_slide(self, background_path, text, output_path,
                     slide_number=1, total_slides=5,
                     is_hook=False, is_cta=False, preset=None):
        """Render a single slide with text overlay."""
        if preset is None:
            preset = random.choice(self.slide_config["presets"])

        try:
            bg = Image.open(background_path).convert("RGBA")
            bg = bg.resize((self.width, self.height), Image.LANCZOS)
        except Exception:
            bg = Image.new("RGBA", (self.width, self.height), (20, 40, 20, 255))

        bg_blurred = bg.filter(ImageFilter.GaussianBlur(radius=2))

        overlay = self._create_gradient_overlay(
            self.width, self.height,
            opacity=preset.get("overlay_opacity", 0.65),
        )

        canvas = Image.alpha_composite(bg_blurred, overlay)
        draw = ImageDraw.Draw(canvas)

        # ─── Brand-aware design elements ───
        accent_color = preset.get("accent_color", self.brand.get("colors", {}).get("secondary", "#FFC107"))

        # Top accent bar
        draw.rectangle([(0, 0), (self.width, 6)], fill=self._hex_to_rgb(accent_color))

        # Brand watermark (top-left)
        brand_font = self._get_font(28, bold=True)
        brand_name = self.brand.get("name", "").upper()
        self._draw_text_with_shadow(
            draw, (40, 40), brand_name,
            font=brand_font, fill=accent_color, shadow_offset=2,
        )

        # Slide indicator dots (top-right)
        dot_y = 48
        dot_start_x = self.width - 40 - (total_slides * 24)
        for i in range(total_slides):
            x = dot_start_x + i * 24
            if i + 1 == slide_number:
                draw.ellipse([(x, dot_y), (x + 14, dot_y + 14)],
                             fill=self._hex_to_rgb(accent_color))
            else:
                draw.ellipse([(x, dot_y), (x + 14, dot_y + 14)],
                             fill=(255, 255, 255, 100))

        # ─── Main Text ───
        text_color = preset.get("text_color", "#FFFFFF")
        margin_x = 80
        max_text_width = self.width - margin_x * 2

        if is_hook:
            font_size = preset.get("font_size_hook", 84)
            font = self._get_font(font_size, bold=True)
            lines = self._wrap_text(text, font, max_text_width)

            line_height = font_size * 1.3
            total_height = len(lines) * line_height
            start_y = (self.height - total_height) / 2

            for i, line in enumerate(lines):
                y = start_y + i * line_height
                bbox = font.getbbox(line)
                x = (self.width - bbox[2]) / 2
                self._draw_text_with_shadow(
                    draw, (x, y), line, font,
                    fill=text_color, shadow_offset=4,
                )

            underline_y = start_y + total_height + 20
            underline_width = min(max_text_width * 0.6, 400)
            underline_x = (self.width - underline_width) / 2
            draw.rectangle(
                [(underline_x, underline_y),
                 (underline_x + underline_width, underline_y + 6)],
                fill=self._hex_to_rgb(accent_color),
            )

        elif is_cta:
            font_size = preset.get("font_size_title", 72)
            font = self._get_font(font_size, bold=True)
            lines = self._wrap_text(text, font, max_text_width)

            line_height = font_size * 1.3
            total_height = len(lines) * line_height
            start_y = (self.height * 0.35)

            for i, line in enumerate(lines):
                y = start_y + i * line_height
                bbox = font.getbbox(line)
                x = (self.width - bbox[2]) / 2
                self._draw_text_with_shadow(
                    draw, (x, y), line, font,
                    fill=text_color, shadow_offset=4,
                )

            # CTA button with brand domain
            cta_font = self._get_font(48, bold=True)
            cta_text = self.brand.get("domain", "")
            if cta_text:
                bbox = cta_font.getbbox(cta_text)
                cta_width = bbox[2] + 80
                cta_height = 80
                cta_x = (self.width - cta_width) / 2
                cta_y = start_y + total_height + 60

                draw.rounded_rectangle(
                    [(cta_x, cta_y), (cta_x + cta_width, cta_y + cta_height)],
                    radius=15,
                    fill=self._hex_to_rgb(accent_color),
                )
                draw.text(
                    (cta_x + 40, cta_y + 12),
                    cta_text,
                    font=cta_font,
                    fill=self._hex_to_rgb("#000000"),
                )

        else:
            font_size = preset.get("font_size_body", 54)
            font = self._get_font(font_size, bold=True)
            lines = self._wrap_text(text, font, max_text_width)

            line_height = font_size * 1.4
            total_height = len(lines) * line_height
            start_y = (self.height - total_height) / 2

            bar_x = margin_x - 30
            bar_top = start_y - 20
            bar_bottom = start_y + total_height + 20
            draw.rectangle(
                [(bar_x, bar_top), (bar_x + 6, bar_bottom)],
                fill=self._hex_to_rgb(accent_color),
            )

            for i, line in enumerate(lines):
                y = start_y + i * line_height
                self._draw_text_with_shadow(
                    draw, (margin_x, y), line, font,
                    fill=text_color, shadow_offset=3,
                )

        # ─── Bottom branding strip ───
        strip_height = 80
        strip_y = self.height - strip_height
        strip_overlay = Image.new("RGBA", (self.width, strip_height), (0, 0, 0, 150))
        canvas.paste(strip_overlay, (0, strip_y), strip_overlay)

        small_font = self._get_font(24, bold=False)
        draw = ImageDraw.Draw(canvas)
        tagline = self.brand.get("tagline", "")
        draw.text(
            (40, strip_y + 28),
            f"🔋 {tagline}",
            font=small_font,
            fill=(255, 255, 255, 200),
        )

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        canvas = canvas.convert("RGB")
        canvas.save(output_path, "JPEG", quality=95)
        return output_path

    def render_all_slides(self, slides, background_paths, output_dir):
        """Render all slides for a scenario."""
        preset = random.choice(self.slide_config["presets"])
        total = len(slides)
        paths = []

        for i, (slide, bg_path) in enumerate(zip(slides, background_paths)):
            filename = f"slide_{slide.slide_number:02d}.jpg"
            output_path = str(Path(output_dir) / filename)

            path = self.render_slide(
                background_path=bg_path,
                text=slide.text_on_screen,
                output_path=output_path,
                slide_number=slide.slide_number,
                total_slides=total,
                is_hook=(i == 0),
                is_cta=(i == total - 1),
                preset=preset,
            )
            paths.append(path)
            print(f"  ✅ Slide {slide.slide_number} rendered")

        return paths
