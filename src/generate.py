#!/usr/bin/env python3
"""
Content Engine — Main Orchestrator
Runs the complete pipeline: scenario → images → slides → TTS → video → upload.
Supports multi-brand: use --brand to select which brand to generate for.

Usage:
    python -m src.generate                          # Default brand (homedome)
    python -m src.generate --brand homedome         # Specific brand
    python -m src.generate --brand my-other-biz     # Another brand
    python -m src.generate --count 3                # Generate 3 videos
    python -m src.generate --pillar fear_hook       # Specific content pillar
    python -m src.generate --no-upload              # Skip upload step
    python -m src.generate --dry-run                # Only generate scenario
    python -m src.generate --list-brands            # Show available brands
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.brand import BrandConfig
from src.scenario import ScenarioGenerator, Scenario
from src.images import ImageGenerator
from src.slides import SlideRenderer
from src.tts import TTSGenerator
from src.video import VideoAssembler
from src.upload import ContentUploader


class ContentEngine:
    """Main orchestrator for the content generation pipeline."""

    def __init__(self, brand_config: BrandConfig):
        self.bc = brand_config
        self.config = brand_config.config
        # Brand-specific output directory
        self.output_base = str(Path("output") / brand_config.brand_id)
        Path(self.output_base).mkdir(parents=True, exist_ok=True)

        print(f"🔋 Content Engine v2.0 — Multi-Brand")
        print(f"🏷️  Brand: {brand_config.brand_name}")
        print(f"🌐 Domain: {brand_config.domain}")
        print(f"🗣️  Language: {brand_config.language}")
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
        scenario_gen = ScenarioGenerator(self.bc)
        scenarios = scenario_gen.generate(count=count, pillar_id=pillar_id)
        print(f"  ✅ Generated {len(scenarios)} scenario(s)")

        for i, scenario in enumerate(scenarios):
            print(f"\n{'='*50}")
            print(f"📹 VIDEO {i+1}/{len(scenarios)}: {scenario.title}")
            print(f"🏷️  Brand: {scenario.brand_id}")
            print(f"🎯 Pillar: {scenario.pillar}")
            print(f"🪝 Hook: {scenario.hook}")
            print(f"{'='*50}")

            video_dir = str(Path(self.output_base) / scenario.id)
            Path(video_dir).mkdir(parents=True, exist_ok=True)

            scenario_path = scenario_gen.save_scenario(scenario, self.output_base)
            print(f"  💾 Scenario saved: {scenario_path}")

            if dry_run:
                results.append({
                    "scenario_id": scenario.id,
                    "brand_id": scenario.brand_id,
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
                    "brand_id": scenario.brand_id,
                    "title": scenario.title,
                    "status": "failed",
                    "error": str(e),
                })

        # ─── Summary ───
        elapsed = time.time() - start_time
        ok_count = len([r for r in results if r.get("status") == "success"])
        print(f"\n{'='*50}")
        print(f"🏁 PIPELINE COMPLETE — {self.bc.brand_name}")
        print(f"⏱️  Total time: {elapsed:.1f}s")
        print(f"📹 Videos: {ok_count}/{len(scenarios)}")

        report_path = Path(self.output_base) / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        report_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
        print(f"📊 Report: {report_path}")

        return results

    def _process_video(self, scenario: Scenario, video_dir: str, skip_upload: bool) -> dict:
        result = {
            "scenario_id": scenario.id,
            "brand_id": scenario.brand_id,
            "title": scenario.title,
            "pillar": scenario.pillar,
        }

        # ─── Step 2: Generate Background Images ───
        print("\n  🎨 STEP 2: Generating background images...")
        img_gen = ImageGenerator(self.bc)
        bg_paths = img_gen.generate_slide_backgrounds(
            slides=scenario.slides, output_dir=video_dir,
        )
        result["backgrounds"] = bg_paths

        # ─── Step 3: Render Slides ───
        print("\n  🖼️  STEP 3: Rendering slides...")
        renderer = SlideRenderer(self.bc)
        slide_paths = renderer.render_all_slides(
            slides=scenario.slides, background_paths=bg_paths,
            output_dir=video_dir,
        )
        result["slides"] = slide_paths

        # ─── Step 4: Generate TTS Audio (with word timestamps) ───
        print("\n  🗣️  STEP 4: Generating TTS audio...")
        tts = TTSGenerator(self.bc)
        audio_paths, word_timings = tts.generate_slide_audio(
            slides=scenario.slides, output_dir=video_dir,
        )
        tts.save_timings(word_timings, video_dir)
        result["audio"] = audio_paths

        # ─── Step 5: Assemble Video ───
        print("\n  🎬 STEP 5: Assembling video...")
        assembler = VideoAssembler(self.bc)
        video_filename = f"{scenario.id}.mp4"
        video_path = str(Path(video_dir) / video_filename)
        assembler.assemble_video(
            slide_paths=slide_paths, audio_paths=audio_paths,
            slides=scenario.slides, output_path=video_path,
            word_timings=word_timings,
        )
        result["video_path"] = video_path

        # ─── Step 6: Upload ───
        if not skip_upload:
            print("\n  📤 STEP 6: Uploading via Post-Bridge...")
            uploader = ContentUploader(self.bc)
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
        description="Content Engine — Generate TikTok/Shorts videos for any brand"
    )
    parser.add_argument(
        "--brand", "-b",
        type=str, default=None,
        help="Brand profile ID (default: from config.yaml)",
    )
    parser.add_argument(
        "--count", "-n",
        type=int, default=1,
        help="Number of videos to generate (default: 1)",
    )
    parser.add_argument(
        "--pillar", "-p",
        type=str, default=None,
        help="Content pillar ID (default: random weighted)",
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
        help="Path to global config file",
    )
    parser.add_argument(
        "--list-brands",
        action="store_true",
        help="List available brand profiles and exit",
    )
    parser.add_argument(
        "--scenarios-only",
        action="store_true",
        help="Generate scenarios and save to disk, skip media generation",
    )
    parser.add_argument(
        "--from-scenario",
        type=str, default=None,
        help="Generate video from a pre-made scenario.json file",
    )

    args = parser.parse_args()
    load_dotenv()

    # List brands mode
    if args.list_brands:
        brands = BrandConfig.list_brands()
        print(f"📋 Available brands ({len(brands)}):")
        for brand_id in brands:
            try:
                bc = BrandConfig(brand_id=brand_id, config_path=args.config)
                print(f"  • {brand_id} — {bc.brand_name} ({bc.domain})")
            except Exception as e:
                print(f"  • {brand_id} — ❌ Error: {e}")
        return

    # Load brand config
    try:
        bc = BrandConfig(brand_id=args.brand, config_path=args.config)
    except FileNotFoundError as e:
        print(f"❌ {e}")
        sys.exit(1)

    engine = ContentEngine(brand_config=bc)

    # Scenarios-only mode: generate and save scenarios, skip media
    if args.scenarios_only:
        scenario_gen = ScenarioGenerator(bc)
        scenarios = scenario_gen.generate(count=args.count, pillar_id=args.pillar)
        print(f"\n📝 Generated {len(scenarios)} scenario(s):")
        for s in scenarios:
            path = scenario_gen.save_scenario(s, engine.output_base)
            print(f"  💾 [{s.pillar}] {s.title} → {path}")
        return

    # From-scenario mode: build video from existing scenario.json
    if args.from_scenario:
        scenario_path = Path(args.from_scenario)
        if not scenario_path.exists():
            print(f"❌ Scenario file not found: {scenario_path}")
            sys.exit(1)
        raw = json.loads(scenario_path.read_text(encoding="utf-8"))
        scenario = Scenario(**raw)
        video_dir = str(scenario_path.parent)
        print(f"\n📹 Building video from scenario: {scenario.title}")
        result = engine._process_video(scenario, video_dir, args.no_upload)
        report_path = Path(video_dir) / "build_result.json"
        report_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"\n{'='*50}")
        print(f"📊 Result: {report_path}")
        if result.get("status") == "failed":
            sys.exit(1)
        return

    results = engine.run_pipeline(
        count=args.count,
        pillar_id=args.pillar,
        skip_upload=args.no_upload,
        dry_run=args.dry_run,
    )

    failed = [r for r in results if r.get("status") == "failed"]
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
