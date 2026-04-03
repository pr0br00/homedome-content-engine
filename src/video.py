"""
Content Engine — Video Assembly Module
Combines slides + audio into final MP4 with dynamic subtitles using ffmpeg.
Multi-brand: uses shared video/subtitle config.
"""

import json
import os
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

    def _generate_srt(self, slides, audio_paths):
        srt_content = ""
        current_time = 0.0
        sub_index = 1

        for slide, audio_path in zip(slides, audio_paths):
            if not audio_path or not os.path.exists(audio_path):
                continue

            duration = self.get_audio_duration(audio_path) + 0.3
            text = slide.tts_script

            if self.sub_config.get("style") == "word_highlight":
                words = text.split()
                chunk_size = 3
                chunks = [
                    " ".join(words[i:i + chunk_size])
                    for i in range(0, len(words), chunk_size)
                ]

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
            else:
                start = self._format_srt_time(current_time)
                end = self._format_srt_time(current_time + duration)
                srt_content += f"{sub_index}\n{start} --> {end}\n{text}\n\n"
                current_time += duration
                sub_index += 1

        return srt_content

    def _format_srt_time(self, seconds):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def assemble_video(self, slide_paths, audio_paths, slides, output_path, add_subtitles=True):
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
                srt_path = os.path.join(tmpdir, "subtitles.srt")
                srt_content = self._generate_srt(slides, audio_paths)
                with open(srt_path, "w", encoding="utf-8") as f:
                    f.write(srt_content)

                font_size = self.sub_config.get("font_size", 48)
                margin_bottom = self.sub_config.get("margin_bottom", 200)

                subtitle_filter = (
                    f"subtitles={srt_path}:force_style='"
                    f"FontSize={font_size},"
                    f"FontName=Arial,"
                    f"PrimaryColour=&H00FFFFFF,"
                    f"OutlineColour=&H00000000,"
                    f"BackColour=&H80000000,"
                    f"Outline=2,Shadow=1,"
                    f"MarginV={margin_bottom},"
                    f"Alignment=2,Bold=1'"
                )

                result = subprocess.run([
                    "ffmpeg", "-y", "-i", merged_path,
                    "-vf", subtitle_filter,
                    "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                    "-c:a", "copy", output_path,
                ], capture_output=True, text=True)

                if result.returncode != 0:
                    print(f"  ⚠️  Subtitle burn failed, copying without subs")
                    subprocess.run(["cp", merged_path, output_path], check=True)
                else:
                    print("  ✅ Subtitles burned in")
            else:
                subprocess.run(["cp", merged_path, output_path], check=True)

        duration = self.get_audio_duration(output_path)
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"  📹 Final video: {duration:.1f}s, {size_mb:.1f}MB")

        return output_path
