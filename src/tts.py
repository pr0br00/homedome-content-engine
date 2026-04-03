"""
Content Engine — Text-to-Speech Module
Uses ElevenLabs API for high-quality TTS with word-level timestamps.
Multi-brand: each brand can have its own voice.
"""

import base64
import json
import os
from pathlib import Path

from elevenlabs import ElevenLabs

from src.brand import BrandConfig


class WordTiming:
    """Word-level timing from ElevenLabs alignment."""
    def __init__(self, word: str, start: float, end: float):
        self.word = word
        self.start = start
        self.end = end

    def __repr__(self):
        return f"WordTiming({self.word!r}, {self.start:.2f}-{self.end:.2f})"


class TTSGenerator:
    """Text-to-Speech generator using ElevenLabs with word-level timestamps."""

    def __init__(self, brand_config: BrandConfig):
        self.config = brand_config.config

        api_key = os.environ.get("ELEVENLABS_API_KEY")
        if not api_key:
            raise ValueError("ELEVENLABS_API_KEY environment variable not set")

        self.client = ElevenLabs(api_key=api_key)
        self.tts_config = self.config["tts"]

        self.voice_id = (
            self.tts_config.get("voice_id")
            or os.environ.get("ELEVENLABS_VOICE_ID")
            or "TX3LPaxmHKxFdv7VOQHJ"
        )

    def _extract_word_timings(self, alignment) -> list[WordTiming]:
        """Extract word-level timings from ElevenLabs character alignment."""
        chars = alignment.characters
        starts = alignment.character_start_times_seconds
        ends = alignment.character_end_times_seconds

        words = []
        current_word = ""
        word_start = 0.0

        for i, char in enumerate(chars):
            if char == " ":
                if current_word:
                    words.append(WordTiming(current_word, word_start, ends[i - 1]))
                    current_word = ""
            else:
                if not current_word:
                    word_start = starts[i]
                current_word += char

        if current_word:
            words.append(WordTiming(current_word, word_start, ends[-1]))

        return words

    def generate_audio_with_timestamps(self, text: str, output_path: str) -> tuple[str, list[WordTiming]]:
        """Generate audio with word-level timestamps for precise subtitle sync."""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        resp = self.client.text_to_speech.convert_with_timestamps(
            voice_id=self.voice_id,
            text=text,
            model_id=self.tts_config.get("model", "eleven_multilingual_v2"),
            voice_settings={
                "stability": self.tts_config.get("stability", 0.5),
                "similarity_boost": self.tts_config.get("similarity_boost", 0.75),
                "style": 0.0,
                "use_speaker_boost": True,
            },
        )

        # Decode audio and save
        audio_bytes = base64.b64decode(resp.audio_base_64)
        with open(output_path, "wb") as f:
            f.write(audio_bytes)

        # Extract word timings
        word_timings = []
        if resp.alignment:
            word_timings = self._extract_word_timings(resp.alignment)

        return output_path, word_timings

    def generate_audio(self, text: str, output_path: str) -> str:
        """Generate audio (without timestamps) — legacy fallback."""
        path, _ = self.generate_audio_with_timestamps(text, output_path)
        return path

    def generate_slide_audio(self, slides: list, output_dir: str) -> tuple[list[str], list[list[WordTiming]]]:
        """Generate TTS audio for all slides with word-level timestamps."""
        paths = []
        all_timings = []
        total_chars = sum(len(s.tts_script) for s in slides)
        print(f"  📊 Total characters: {total_chars}")

        for slide in slides:
            filename = f"audio_slide_{slide.slide_number:02d}.mp3"
            output_path = str(Path(output_dir) / filename)
            try:
                path, timings = self.generate_audio_with_timestamps(
                    text=slide.tts_script,
                    output_path=output_path,
                )
                paths.append(path)
                all_timings.append(timings)
                print(f"  ✅ Slide {slide.slide_number} audio generated "
                      f"({len(slide.tts_script)} chars, {len(timings)} words)")
            except Exception as e:
                print(f"  ❌ Slide {slide.slide_number} TTS failed: {e}")
                paths.append("")
                all_timings.append([])

        return paths, all_timings

    def save_timings(self, all_timings: list[list[WordTiming]], output_dir: str):
        """Save word timings to JSON for debugging/verification."""
        data = []
        for i, timings in enumerate(all_timings):
            data.append({
                "slide": i + 1,
                "words": [{"word": t.word, "start": t.start, "end": t.end} for t in timings],
            })
        path = Path(output_dir) / "word_timings.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    bc = BrandConfig()
    tts = TTSGenerator(bc)

    path, timings = tts.generate_audio_with_timestamps(
        text="Привіт! Це тестове повідомлення.",
        output_path="output/test_audio.mp3",
    )
    print(f"✅ Test audio: {path}")
    for t in timings:
        print(f"  {t.word}: {t.start:.2f}s - {t.end:.2f}s")
