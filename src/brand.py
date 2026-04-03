"""
Content Engine — Brand Configuration Loader
Merges global config.yaml with brand-specific brands/<id>.yaml.
"""

import os
import yaml
from pathlib import Path
from typing import Optional


def deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dicts. Override values take precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class BrandConfig:
    """Loads and merges global + brand-specific configuration."""

    def __init__(
        self,
        brand_id: Optional[str] = None,
        config_path: str = "config.yaml",
        brands_dir: str = "brands",
    ):
        self.config_path = config_path
        self.brands_dir = brands_dir

        # Load global config
        with open(config_path) as f:
            self.global_config = yaml.safe_load(f)

        # Determine brand ID
        self.brand_id = brand_id or self.global_config.get("default_brand", "homedome")

        # Load brand config
        brand_path = Path(brands_dir) / f"{self.brand_id}.yaml"
        if not brand_path.exists():
            available = self.list_brands()
            raise FileNotFoundError(
                f"Brand profile not found: {brand_path}\n"
                f"Available brands: {', '.join(available)}\n"
                f"Create a new brand: cp brands/_template.yaml brands/{self.brand_id}.yaml"
            )

        with open(brand_path) as f:
            self.brand_config = yaml.safe_load(f)

        # Merge: global is the base, brand overrides specific sections
        self.config = self._build_merged_config()

    def _build_merged_config(self) -> dict:
        """Build the final merged config."""
        merged = self.global_config.copy()

        # Brand section (entirely from brand file)
        merged["brand"] = self.brand_config.get("brand", {})

        # TTS: merge global defaults with brand overrides
        global_tts = self.global_config.get("tts", {})
        brand_tts = self.brand_config.get("tts", {})
        merged["tts"] = deep_merge(global_tts, brand_tts)

        # Scenario: merge global defaults with brand-specific pillars & prompt
        global_scenario = self.global_config.get("scenario", {})
        brand_scenario = self.brand_config.get("scenario", {})
        merged["scenario"] = deep_merge(global_scenario, brand_scenario)

        # Slides: use brand presets if available, else global
        if "slides" in self.brand_config and self.brand_config["slides"]:
            merged["slides"] = deep_merge(
                self.global_config.get("slides", {}),
                self.brand_config["slides"],
            )

        # Upload: merge platform configs
        global_upload = self.global_config.get("upload", {})
        brand_upload = self.brand_config.get("upload", {})
        merged["upload"] = deep_merge(global_upload, brand_upload)

        return merged

    @property
    def brand(self) -> dict:
        return self.config.get("brand", {})

    @property
    def brand_name(self) -> str:
        return self.brand.get("name", self.brand_id)

    @property
    def domain(self) -> str:
        return self.brand.get("domain", "")

    @property
    def language(self) -> str:
        return self.brand.get("language", "uk")

    @property
    def system_prompt(self) -> str:
        return self.config.get("scenario", {}).get("system_prompt", "")

    @property
    def pillars(self) -> list:
        return self.config.get("scenario", {}).get("pillars", [])

    @property
    def pillar_ids(self) -> list[str]:
        return [p["id"] for p in self.pillars]

    @property
    def post_bridge_accounts(self) -> list[int]:
        """Get brand-specific Post-Bridge account IDs."""
        return self.config.get("upload", {}).get("post_bridge_accounts", [])

    @staticmethod
    def list_brands(brands_dir: str = "brands") -> list[str]:
        """List available brand profile IDs."""
        brands = []
        brands_path = Path(brands_dir)
        if brands_path.exists():
            for f in brands_path.glob("*.yaml"):
                if f.stem != "_template":
                    brands.append(f.stem)
        return sorted(brands)

    def __getitem__(self, key):
        return self.config[key]

    def get(self, key, default=None):
        return self.config.get(key, default)


# ─── CLI ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    brands = BrandConfig.list_brands()
    print(f"📋 Available brands: {', '.join(brands)}")

    brand_id = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        bc = BrandConfig(brand_id=brand_id)
        print(f"\n🏷️  Brand: {bc.brand_name}")
        print(f"🌐 Domain: {bc.domain}")
        print(f"🗣️  Language: {bc.language}")
        print(f"🎯 Pillars: {', '.join(bc.pillar_ids)}")
        print(f"📤 Post-Bridge accounts: {bc.post_bridge_accounts}")
    except FileNotFoundError as e:
        print(f"❌ {e}")
