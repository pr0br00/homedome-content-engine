"""
HomeDome Content Engine — Upload Module
Handles auto-upload to TikTok and YouTube Shorts via Post-Bridge API.

Post-Bridge API docs: https://api.post-bridge.com/reference
Supports: TikTok, YouTube, Instagram, Facebook, LinkedIn, Twitter/X,
          Threads, Pinterest, Bluesky.
"""

import os
import json
import yaml
import time
import requests
from pathlib import Path
from typing import Optional

from src.brand import BrandConfig


# ─── Post-Bridge API Client ─────────────────────────────────────

class PostBridgeClient:
    """Low-level client for Post-Bridge API."""

    BASE_URL = "https://api.post-bridge.com/v1"

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get("POST_BRIDGE_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "POST_BRIDGE_API_KEY not set. "
                "Get your API key at https://www.post-bridge.com → Settings → API Keys"
            )

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, endpoint: str, **kwargs) -> dict:
        """Make an API request with error handling."""
        url = f"{self.BASE_URL}{endpoint}"
        resp = requests.request(method, url, headers=self._headers(), **kwargs)

        if resp.status_code >= 400:
            raise Exception(
                f"Post-Bridge API error {resp.status_code}: {resp.text}"
            )

        return resp.json() if resp.text else {}

    # --- Social Accounts ---

    def list_accounts(self, platform: str = None) -> list[dict]:
        """List connected social media accounts."""
        params = {}
        if platform:
            params["platform"] = platform
        data = self._request("GET", "/social-accounts", params=params)
        return data.get("data", [])

    def get_account(self, account_id: int) -> dict:
        """Get a specific social account."""
        return self._request("GET", f"/social-accounts/{account_id}")

    # --- Media Upload ---

    def upload_media(self, file_path: str) -> str:
        """Upload a media file and return the media_id.

        Two-step process:
        1. Request a signed upload URL from Post-Bridge
        2. Upload the binary file to that URL
        """
        path = Path(file_path)
        file_size = path.stat().st_size

        # Determine MIME type
        mime_map = {
            ".mp4": "video/mp4",
            ".mov": "video/quicktime",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
        }
        mime_type = mime_map.get(path.suffix.lower(), "video/mp4")

        # Step 1: Get upload URL
        upload_data = self._request("POST", "/media/create-upload-url", json={
            "name": path.name,
            "mime_type": mime_type,
            "size_bytes": file_size,
        })

        media_id = upload_data.get("media_id") or upload_data.get("data", {}).get("media_id")
        upload_url = upload_data.get("upload_url") or upload_data.get("data", {}).get("upload_url")

        if not media_id or not upload_url:
            raise Exception(f"Post-Bridge: Failed to get upload URL. Response: {upload_data}")

        # Step 2: Upload binary file
        with open(file_path, "rb") as f:
            upload_resp = requests.put(
                upload_url,
                headers={"Content-Type": mime_type},
                data=f,
            )

        if upload_resp.status_code >= 400:
            raise Exception(
                f"Post-Bridge: File upload failed ({upload_resp.status_code}): {upload_resp.text}"
            )

        print(f"  📦 Media uploaded: {media_id} ({file_size / 1024 / 1024:.1f} MB)")
        return media_id

    # --- Posts ---

    def create_post(
        self,
        caption: str,
        account_ids: list[int],
        media_ids: list[str] = None,
        scheduled_at: str = None,
        platform_configs: dict = None,
    ) -> dict:
        """Create a post (instant or scheduled).

        Args:
            caption: Post text/description
            account_ids: List of social account IDs to post to
            media_ids: List of media_id strings from upload_media()
            scheduled_at: ISO-8601 datetime for scheduled posting, or None for instant
            platform_configs: Platform-specific overrides (tiktok, youtube, etc.)
        """
        body = {
            "caption": caption,
            "social_accounts": account_ids,
            "is_draft": False,
        }

        if media_ids:
            body["media"] = media_ids

        if scheduled_at:
            body["scheduled_at"] = scheduled_at

        if platform_configs:
            body["platform_configurations"] = platform_configs

        return self._request("POST", "/posts", json=body)

    def get_post(self, post_id: int) -> dict:
        """Get post details including publish status."""
        return self._request("GET", f"/posts/{post_id}")

    def list_post_results(self, post_id: int = None) -> list[dict]:
        """Get publishing results for a post."""
        params = {}
        if post_id:
            params["post_id"] = post_id
        data = self._request("GET", "/post-results", params=params)
        return data.get("data", [])

    # --- Analytics ---

    def get_analytics(self, timeframe: str = "7d") -> list[dict]:
        """Get analytics across all posts."""
        data = self._request("GET", "/analytics", params={"timeframe": timeframe})
        return data.get("data", [])

    def sync_analytics(self, platform: str = None) -> dict:
        """Trigger analytics sync."""
        body = {}
        if platform:
            body["platform"] = platform
        return self._request("POST", "/analytics/sync", json=body)


# ─── Content Uploader (High-Level) ──────────────────────────────

class ContentUploader:
    """High-level uploader that publishes to TikTok + YouTube via Post-Bridge.

    Supports multi-brand: each brand can specify its own Post-Bridge account IDs,
    or auto-detect from connected accounts by platform.
    """

    def __init__(self, brand_config: BrandConfig):
        self.config = brand_config.config
        self.bc = brand_config
        self.client = PostBridgeClient()
        self._accounts_cache = None

    def _get_accounts(self) -> list[dict]:
        """Get and cache connected accounts."""
        if self._accounts_cache is None:
            self._accounts_cache = self.client.list_accounts()
            if not self._accounts_cache:
                print("  ⚠️  No social accounts connected in Post-Bridge!")
                print("     Connect accounts at: https://www.post-bridge.com/onboarding/connect")
        return self._accounts_cache

    def _find_account_ids(self, platforms: list[str]) -> list[int]:
        """Find account IDs for specified platforms."""
        accounts = self._get_accounts()
        ids = []
        for acc in accounts:
            if acc.get("platform") in platforms:
                ids.append(acc["id"])
                print(f"  📱 Found {acc['platform']} account: @{acc.get('username', '?')}")
        return ids

    def upload_all(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list[str],
        hashtags: list[str],
        scheduled_at: str = None,
    ) -> dict:
        """Upload video to all enabled platforms via Post-Bridge.

        Returns dict with post_id and per-platform results.
        """
        results = {}
        upload_config = self.config.get("upload", {})

        # Determine which platforms to post to
        target_platforms = []
        if upload_config.get("tiktok", {}).get("enabled", False):
            target_platforms.append("tiktok")
        if upload_config.get("youtube", {}).get("enabled", False):
            target_platforms.append("youtube")

        if not target_platforms:
            print("  ⚠️  No platforms enabled in config")
            return results

        # Use brand-specific account IDs if configured, otherwise auto-detect
        brand_account_ids = self.bc.post_bridge_accounts
        if brand_account_ids:
            account_ids = brand_account_ids
            print(f"  📱 Using brand-specific accounts: {account_ids}")
        else:
            account_ids = self._find_account_ids(target_platforms)

        if not account_ids:
            print("  ❌ No matching accounts found in Post-Bridge")
            print(f"     Looking for: {', '.join(target_platforms)}")
            print("     Connect accounts at: https://www.post-bridge.com/onboarding/connect")
            return results

        # Step 1: Upload video file
        print(f"\n  📤 Uploading video to Post-Bridge...")
        try:
            media_id = self.client.upload_media(video_path)
            results["media_id"] = media_id
        except Exception as e:
            print(f"  ❌ Media upload failed: {e}")
            results["error"] = str(e)
            return results

        # Step 2: Build caption with hashtags
        hashtag_str = " ".join(hashtags[:8])
        caption = f"{description}\n\n{hashtag_str}\n\n🔋 homedome.com.ua"

        # Step 3: Build platform-specific configurations
        platform_configs = {}

        if "tiktok" in target_platforms:
            tt_title = f"{title} {' '.join(hashtags[:5])}"
            platform_configs["tiktok"] = {
                "caption": caption,
                "media": [media_id],
                "title": tt_title[:150],
            }

        if "youtube" in target_platforms:
            yt_title = title
            if "#Shorts" not in yt_title:
                yt_title = f"{yt_title} #Shorts"
            if len(yt_title) > 100:
                yt_title = yt_title[:97] + "..."

            yt_caption = f"{description}\n\n{hashtag_str}\n\n🔋 Деталі: homedome.com.ua"
            platform_configs["youtube"] = {
                "caption": yt_caption,
                "media": [media_id],
                "title": yt_title,
            }

        # Step 4: Create the post
        print(f"  📝 Creating post for: {', '.join(target_platforms)}...")
        try:
            post_data = self.client.create_post(
                caption=caption,
                account_ids=account_ids,
                media_ids=[media_id],
                scheduled_at=scheduled_at,
                platform_configs=platform_configs,
            )

            post_id = post_data.get("id") or post_data.get("data", {}).get("id")
            results["post_id"] = post_id
            results["status"] = "scheduled" if scheduled_at else "published"

            if scheduled_at:
                print(f"  📅 Post scheduled for: {scheduled_at}")
            else:
                print(f"  ✅ Post published! (ID: {post_id})")

            # Wait a moment and check results
            if not scheduled_at and post_id:
                time.sleep(3)
                try:
                    post_results = self.client.list_post_results(post_id)
                    for pr in post_results:
                        platform = pr.get("platform", "unknown")
                        status = pr.get("status", "unknown")
                        url = pr.get("url", "")
                        results[platform] = {
                            "status": status,
                            "url": url,
                        }
                        if url:
                            print(f"  🔗 {platform}: {url}")
                        else:
                            print(f"  📊 {platform}: {status}")
                except Exception as e:
                    print(f"  ⚠️  Could not fetch post results: {e}")

        except Exception as e:
            print(f"  ❌ Post creation failed: {e}")
            results["error"] = str(e)

        return results


# ─── CLI ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    print("🔌 Post-Bridge Upload Module")
    print("=" * 40)

    try:
        client = PostBridgeClient()
        accounts = client.list_accounts()
        print(f"\n📱 Connected accounts ({len(accounts)}):")
        for acc in accounts:
            print(f"  • {acc.get('platform', '?')} — @{acc.get('username', '?')} (ID: {acc.get('id')})")

        if not accounts:
            print("  No accounts connected!")
            print("  → Connect at: https://www.post-bridge.com/onboarding/connect")
    except Exception as e:
        print(f"❌ Error: {e}")
