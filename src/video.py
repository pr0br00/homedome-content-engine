"""
Content Engine — Video Assembly Module
Combines slides + audio into final MP4 with dynamic subtitles using ffmpeg.
Multi-brand: uses shared video/subtitle config.
"""

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from src.brand import BrandConfig


class VideoAssembler:
    """Assembles slides and audio into final video with subtitles."""

    def __init__(self, brand_config: BrandConfig):
        self.config = brand_config.config
        self.video_config = self.config["video"]
        self.sub_config = self.config.get("subtitles", {})
        self.width = self.video_config["width"]
        self.height = self.video_config["height"]
        self.fps = self.video_config.get("fps", 30)

        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        except FileNotFoundError:
            raise RuntimeError("ffmpeg not found. Please install ffmpeg.")

    def get_audio_duration(self, audio_path: str) -> float:
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format", audio_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])

    def _create_slide_video(self, slide_path, audio_path, output_path, add_zoom=True):
        duration = self.get_audio_duration(audio_path) + 0.3

        if add_zoom:
            vf = (
                f"scale={self.width * 2}:{self.height * 2},"
                f"zoompan=z='min(zoom+0.0003,1.05)':"
                f"d={int(duration * self.fps)}:"
                f"x='iw/2-(iw/zoom/2)':"
                f"y='ih/2-(ih/zoom/2)':"
                f"s={self.width}x{self.height}:fps={self.fps},"
                f"format=yuv420p"
            )
        else:
            vf = f"scale={self.width}:{self.height},format=yuv420p"

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", slide_path,
            "-i", audio_path,
            "-vf", vf,
            "-c:v", self.video_config.get("codec", "libx264"),
            "-preset", "medium", "-crf", "23",
            "-c:a", self.video_config.get("audio_codec", "aac"),
            "-b:a", "128k",
            "-t", str(duration),
            "-pix_fmt", "yuv420p",
            "-shortest", output_path,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"⚠️  ffmpeg error: {result.stderr[-500:]}")
            cmd_simple = [
                "ffmpeg", "-y",
                "-loop", "1", "-i", slide_path,
                "-i", audio_path,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-t", str(duration), "-pix_fmt", "yuv420p",
                "-vf", f"scale={self.width}:{self.height}",
                "-shortest", output_path,
            ]
            subprocess.run(cmd_simple, capture_output=True, text=True, check=True)

        return output_path

    def _generate_ass(self, slides, audio_paths, word_timings=None):
        """Generate ASS subtitle file with keyword highlighting.

        Uses yellow (#FFFF00) as the main subtitle color.
        Keywords from each slide are highlighted in white (#FFFFFF) with bold
        to create a pop-out contrast effect against the yellow base.
        """
        main_color = self.sub_config.get("color", "#FFFF00")
        highlight_color = self.sub_config.get("highlight_color", "#FFFFFF")
        font_size = self.sub_config.get("font_size", 52)
        margin_bottom = self.sub_config.get("margin_bottom", 180)

        def rgb_to_ass(hex_color):
            """Convert #RRGGBB to &HBBGGRR& ASS format."""
            h = hex_color.lstrip("#")
            if len(h) >= 6:
                r, g, b = h[0:2], h[2:4], h[4:6]
                return f"&H00{b}{g}{r}&"
            return "&H0000FFFF&"

        ass_main = rgb_to_ass(main_color)
        ass_highlight = rgb_to_ass(highlight_color)

        # Detect font
        font_name = "Arial"
        for fp in ["fonts/Montserrat-Bold.ttf", "fonts/Montserrat-Black.ttf"]:
            if os.path.exists(fp):
                font_name = "Montserrat"
                break

        # ASS header
        ass_content = f"""[Script Info]
Title: Content Engine Subtitles
ScriptType: v4.00+
PlayResX: {self.width}
PlayResY: {self.height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},{ass_main},&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,40,40,{margin_bottom},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

        current_time = 0.0
        slide_timings = word_timings if word_timings else [None] * len(slides)

        for idx, (slide, audio_path) in enumerate(zip(slides, audio_paths)):
            if not audio_path or not os.path.exists(audio_path):
                continue

            duration = self.get_audio_duration(audio_path) + 0.3
            keywords = getattr(slide, 'keywords', []) or []
            timings = slide_timings[idx] if idx < len(slide_timings) else None

            if timings and len(timings) > 0:
                # Use real word-level timestamps from ElevenLabs
                chunk_size = 3
                for i in range(0, len(timings), chunk_size):
                    chunk_words = timings[i:i + chunk_size]
                    chunk_text = " ".join(w.word for w in chunk_words)
                    chunk_start = current_time + chunk_words[0].start
                    chunk_end = current_time + chunk_words[-1].end + 0.05
                    start = self._format_ass_time(chunk_start)
                    end = self._format_ass_time(chunk_end)
                    styled = self._highlight_keywords(chunk_text, keywords, ass_highlight)
                    ass_content += f"Dialogue: 0,{start},{end},Default,,0,0,0,,{styled}\n"
                current_time += duration
            else:
                # Fallback: equal timing distribution
                text = slide.tts_script
                words = text.split()
                chunk_size = 3
                chunks = [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]
                if chunks:
                    chunk_duration = duration / len(chunks)
                    for chunk in chunks:
                        start = self._format_ass_time(current_time)
                        end = self._format_ass_time(current_time + chunk_duration)
                        styled = self._highlight_keywords(chunk, keywords, ass_highlight)
                        ass_content += f"Dialogue: 0,{start},{end},Default,,0,0,0,,{styled}\n"
                        current_time += chunk_duration
                else:
                    current_time += duration

        return ass_content

    def _highlight_keywords(self, text, keywords, highlight_ass_color):
        """Highlight keyword matches in text using ASS override tags."""
        if not keywords:
            return text

        result = text
        for kw in keywords:
            pattern = re.compile(re.escape(kw), re.IGNORECASE)
            result = pattern.sub(
                lambda m: f"{{\\c{highlight_ass_color}\\b1}}{m.group()}{{\\r}}",
                result,
            )
        return result

    def _format_ass_time(self, seconds):
        """Format time as H:MM:SS.CC for ASS format."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        centis = int((seconds % 1) * 100)
        return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"

    def _generate_srt_fallback(self, slides, audio_paths, srt_path):
        """Generate simple SRT file as fallback if ASS fails."""
        srt_content = ""
        current_time = 0.0
        sub_index = 1

        for slide, audio_path in zip(slides, audio_paths):
            if not audio_path or not os.path.exists(audio_path):
                continue
            duration = self.get_audio_duration(audio_path) + 0.3
            text = slide.tts_script
            words = text.split()
            chunk_size = 3
            chunks = [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]
            if chunks:
                chunk_duration = duration / len(chunks)
                for chunk in chunks:
                    start = self._format_srt_time(current_time)
                    end = self._format_srt_time(current_time + chunk_duration)
                    srt_content += f"{sub_index}\n{start} --> {end}\n{chunk}\n\n"
                    current_time += chunk_duration
                    sub_index += 1
            else:
                current_time += duration

        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_content)

    def _format_srt_time(self, seconds):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def assemble_video(self, slide_paths, audio_paths, slides, output_path, add_subtitles=True, word_timings=None):
        """Assemble final video from slides + audio."""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            segment_paths = []
            for i, (slide_img, audio) in enumerate(zip(slide_paths, audio_paths)):
                if not audio or not os.path.exists(audio):
                    print(f"  ⚠️  Skipping slide {i+1} (no audio)")
                    continue

                segment_path = os.path.join(tmpdir, f"segment_{i:02d}.mp4")
                self._create_slide_video(
                    slide_path=slide_img, audio_path=audio,
                    output_path=segment_path, add_zoom=True,
                )
                segment_paths.append(segment_path)
                print(f"  ✅ Segment {i+1}/{len(slide_paths)} created")

            if not segment_paths:
                raise RuntimeError("No video segments were created")

            concat_list = os.path.join(tmpdir, "concat.txt")
            with open(concat_list, "w") as f:
                for sp in segment_paths:
                    f.write(f"file '{sp}'\n")

            merged_path = os.path.join(tmpdir, "merged.mp4")
            subprocess.run([
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", concat_list, "-c", "copy", merged_path,
            ], capture_output=True, text=True, check=True)
            print("  ✅ Segments merged")

            if add_subtitles and self.sub_config.get("enabled", True):
                ass_path = os.path.join(tmpdir, "subtitles.ass")
                ass_content = self._generate_ass(slides, audio_paths, word_timings=word_timings)
                with open(ass_path, "w", encoding="utf-8") as f:
                    f.write(ass_content)

                # Build fontsdir option if custom fonts exist
                fonts_opt = ""
                if os.path.exists("fonts"):
                    fonts_opt = f":fontsdir=fonts"

                subtitle_filter = f"ass={ass_path}{fonts_opt}"

                result = subprocess.run([
                    "ffmpeg", "-y", "-i", merged_path,
                    "-vf", subtitle_filter,
                    "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                    "-c:a", "copy", output_path,
                ], capture_output=True, text=True)

                if result.returncode != 0:
                    print(f"  ⚠️  ASS subtitle burn failed: {result.stderr[-300:]}")
                    print(f"  ⚠️  Trying SRT fallback...")
                    # Fallback to simple SRT with yellow styling
                    srt_path = os.path.join(tmpdir, "subtitles_fallback.srt")
                    self._generate_srt_fallback(slides, audio_paths, srt_path)
                    font_size = self.sub_config.get("font_size", 52)
                    margin_bottom = self.sub_config.get("margin_bottom", 180)
                    subtitle_filter = (
                        f"subtitles={srt_path}:force_style='"
                        f"FontSize={font_size},"
                        f"FontName=Montserrat,"
                        f"PrimaryColour=&H0000FFFF,"
                        f"OutlineColour=&H00000000,"
                        f"BackColour=&H80000000,"
                        f"Outline=3,Shadow=1,"
                        f"MarginV={margin_bottom},"
                        f"Alignment=2,Bold=1'"
                    )
                    result2 = subprocess.run([
                        "ffmpeg", "-y", "-i", merged_path,
                        "-vf", subtitle_filter,
                        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                        "-c:a", "copy", output_path,
                    ], capture_output=True, text=True)
                    if result2.returncode != 0:
                        print(f"  ⚠️  SRT fallback also failed, copying without subs")
                        subprocess.run(["cp", merged_path, output_path], check=True)
                    else:
                        print("  ✅ Yellow subtitles burned in (SRT fallback)")
                else:
                    print("  ✅ Yellow subtitles with keyword highlighting burned in")
            else:
                subprocess.run(["cp", merged_path, output_path], check=True)

        duration = self.get_audio_duration(output_path)
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"  📹 Final video: {duration:.1f}s, {size_mb:.1f}MB")

        return output_path
