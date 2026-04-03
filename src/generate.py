#!/usr/bin/env python3
"""
HomeDome Content Engine — Main Orchestrator
Runs the complete pipeline: scenario → images → slides → TTS → video → upload.

Usage:
    python -m src.generate                    # Generate 1 video (random pillar)
    python -m src.generate --count 3          # Generate 3 videos
    python -m src.generate --pillar fear_hook # Specific content pillar
    python -m src.generate --no-upload        # Skip upload step
    python -m src.generate --dry-run          # Only generate scenario, no media
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.scenario import ScenarioGenerator, Scenario
from src.images import ImageGenerator
from src.slides import SlideRenderer
from src.tts import TTSGenerator
from src.video import VideoAssembler
from src.upload import ContentUploader


class ContentEngine:
    """Main orchestrator for the content generation pipeline."""

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.output_base = "output"
        Path(self.output_base).mkdir(exist_ok=True)

        print("🔋 HomeDome Content Engine v1.0")
        print("=" * 50)

    def run_pipeline(
        self,
        count: int = 1,
        pillar_id: str = None,
        skip_upload: bool = False,
        dry_run: bool = False,
    ) -> list[dict]:
        """Run the complete content generation pipeline."""
        results = []
        start_time = time.time()

        # ─── Step 1: Generate Scenarios ───
        print("\n📝 STEP 1: Generating scenarios...")
        scenario_gen = ScenarioGenerator(self.config_path)
        scenarios = scenario_gen.generate(count=count, pillar_id=pillar_id)
        print(f"  ✅ Generated {len(scenarios)} scenario(s)")

        for i, scenario in enumerate(scenarios):
            print(f"\n{'='*50}")
            print(f"📹 VIDEO {i+1}/{len(scenarios)}: {scenario.title}")
            print(f"🎯 Pillar: {scenario.pillar}")
            print(f"🪝 Hook: {scenario.hook}")
            print(f"{'='*50}")

            video_dir = str(Path(self.output_base) / scenario.id)
            Path(video_dir).mkdir(parents=True, exist_ok=True)

            # Save scenario
            scenario_path = scenario_gen.save_scenario(scenario, self.output_base)
            print(f"  💾 Scenario saved: {scenario_path}")

            if dry_run:
                results.append({
                    "scenario_id": scenario.id,
                    "title": scenario.title,
                    "status": "dry_run",
                    "scenario_path": scenario_path,
                })
                continue

            try:
                result = self._process_video(scenario, video_dir, skip_upload)
                results.append(result)
            except Exception as e:
                print(f"\n  ❌ FAILED: {e}")
                results.append({
                    "scenario_id": scenario.id,
                    "title": scenario.title,
                    "status": "failed",
                    "error": str(e),
                })

        # ─── Summary ───
        elapsed = time.time() - start_time
        print(f"\n{'='*50}")
        print(f"🏁 PIPELINE COMPLETE")
        print(f"⏱️  Total time: {elapsed:.1f}s")
        print(f"📹 Videos: {len([r for r in results if r.get('status') == 'success'])}/{len(scenarios)}")

        # Save run report
        report_path = Path(self.output_base) / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        report_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
        print(f"📊 Report: {report_path}")

        return results

    def _process_video(
        self,
        scenario: Scenario,
        video_dir: str,
        skip_upload: bool,
    ) -> dict:
        """Process a single video through the pipeline."""
        result = {
            "scenario_id": scenario.id,
            "title": scenario.title,
            "pillar": scenario.pillar,
        }

        # ─── Step 2: Generate Background Images ───
        print("\n  🎨 STEP 2: Generating background images...")
        img_gen = ImageGenerator(self.config_path)
        bg_paths = img_gen.generate_slide_backgrounds(
            slides=scenario.slides,
            output_dir=video_dir,
        )
        result["backgrounds"] = bg_paths

        # ─── Step 3: Render Slides ───
        print("\n  🖼️  STEP 3: Rendering slides...")
        renderer = SlideRenderer(self.config_path)
        slide_paths = renderer.render_all_slides(
            slides=scenario.slides,
            background_paths=bg_paths,
            output_dir=video_dir,
        )
        result["slides"] = slide_paths

        # ─── Step 4: Generate TTS Audio ───
        print("\n  🗣️  STEP 4: Generating TTS audio...")
        tts = TTSGenerator(self.config_path)
        audio_paths = tts.generate_slide_audio(
            slides=scenario.slides,
            output_dir=video_dir,
        )
        result["audio"] = audio_paths

        # ─── Step 5: Assemble Video ───
        print("\n  🎬 STEP 5: Assembling video...")
        assembler = VideoAssembler(self.config_path)
        video_filename = f"{scenario.id}.mp4"
        video_path = str(Path(video_dir) / video_filename)
        assembler.assemble_video(
            slide_paths=slide_paths,
            audio_paths=audio_paths,
            slides=scenario.slides,
            output_path=video_path,
        )
        result["video_path"] = video_path

        # ─── Step 6: Upload ───
        if not skip_upload:
            print("\n  📤 STEP 6: Uploading...")
            uploader = ContentUploader(self.config_path)
            upload_results = uploader.upload_all(
                video_path=video_path,
                title=scenario.title,
                description=scenario.description,
                tags=scenario.hashtags,
                hashtags=scenario.hashtags,
            )
            result["uploads"] = upload_results
        else:
            print("\n  ⏭️  STEP 6: Upload skipped")
            result["uploads"] = {}

        result["status"] = "success"
        print(f"\n  ✅ VIDEO COMPLETE: {scenario.title}")
        return result


# ─── CLI ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="HomeDome Content Engine — Generate TikTok/Shorts videos"
    )
    parser.add_argument(
        "--count", "-n",
        type=int, default=1,
        help="Number of videos to generate (default: 1)",
    )
    parser.add_argument(
        "--pillar", "-p",
        type=str, default=None,
        choices=["fear_hook", "education", "comparison", "case_study", "myth_bust", "news_trend"],
        help="Content pillar (default: random weighted)",
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Skip upload step",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only generate scenario, skip media generation",
    )
    parser.add_argument(
        "--config", "-c",
        type=str, default="config.yaml",
        help="Path to config file",
    )

    args = parser.parse_args()

    # Load environment variables
    load_dotenv()

    engine = ContentEngine(config_path=args.config)
    results = engine.run_pipeline(
        count=args.count,
        pillar_id=args.pillar,
        skip_upload=args.no_upload,
        dry_run=args.dry_run,
    )

    # Exit with error if any failed
    failed = [r for r in results if r.get("status") == "failed"]
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
