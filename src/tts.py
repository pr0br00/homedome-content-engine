"""
Content Engine — Text-to-Speech Module
Uses ElevenLabs API for high-quality TTS.
Multi-brand: each brand can have its own voice.
"""

import os
from pathlib import Path

from elevenlabs import ElevenLabs

from src.brand import BrandConfig


class TTSGenerator:
    """Text-to-Speech generator using ElevenLabs."""

    def __init__(self, brand_config: BrandConfig):
        self.config = brand_config.config

        api_key = os.environ.get("ELEVENLABS_API_KEY")
        if not api_key:
            raise ValueError("ELEVENLABS_API_KEY environment variable not set")

        self.client = ElevenLabs(api_key=api_key)
        self.tts_config = self.config["tts"]

        # Brand-specific voice (with fallback to env var, then config default)
        self.voice_id = (
            self.tts_config.get("voice_id")
            or os.environ.get("ELEVENLABS_VOICE_ID")
            or "TX3LPaxmHKxFdv7VOQHJ"
        )

    def generate_audio(self, text: str, output_path: str) -> str:
        """Generate audio from text and save to MP3 file."""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        audio_generator = self.client.text_to_speech.convert(
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

        with open(output_path, "wb") as f:
            for chunk in audio_generator:
                f.write(chunk)

        return output_path

    def generate_slide_audio(self, slides: list, output_dir: str) -> list[str]:
        """Generate TTS audio for all slides."""
        paths = []
        total_chars = sum(len(s.tts_script) for s in slides)
        print(f"  📊 Total characters: {total_chars}")

        for slide in slides:
            filename = f"audio_slide_{slide.slide_number:02d}.mp3"
            output_path = str(Path(output_dir) / filename)
            try:
                path = self.generate_audio(
                    text=slide.tts_script,
                    output_path=output_path,
                )
                paths.append(path)
                print(f"  ✅ Slide {slide.slide_number} audio generated "
                      f"({len(slide.tts_script)} chars)")
            except Exception as e:
                print(f"  ❌ Slide {slide.slide_number} TTS failed: {e}")
                paths.append("")

        return paths

    def get_audio_duration(self, audio_path: str) -> float:
        """Get duration of an audio file in seconds."""
        try:
            from mutagen.mp3 import MP3
            audio = MP3(audio_path)
            return audio.info.length
        except Exception:
            size = os.path.getsize(audio_path)
            return size / (16 * 1024 / 8)

    def get_usage(self) -> dict:
        """Get current ElevenLabs usage stats."""
        try:
            user = self.client.user.get()
            subscription = user.subscription
            return {
                "character_count": subscription.character_count,
                "character_limit": subscription.character_limit,
                "remaining": subscription.character_limit - subscription.character_count,
                "tier": subscription.tier,
            }
        except Exception as e:
            return {"error": str(e)}


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    bc = BrandConfig()
    tts = TTSGenerator(bc)

    usage = tts.get_usage()
    print(f"📊 ElevenLabs usage: {usage}")

    tts.generate_audio(
        text="Привіт! Це тестове повідомлення.",
        output_path="output/test_audio.mp3",
    )
    print("✅ Test audio generated")
