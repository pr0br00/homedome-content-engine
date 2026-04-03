"""
HomeDome Content Engine — Upload Module
Handles auto-upload to Google Drive, YouTube Shorts, and TikTok.
"""

import os
import json
import yaml
import time
import requests
from pathlib import Path
from typing import Optional

# Google APIs
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


# ─── Google Drive Uploader ─────────────────────────────────────────

class GoogleDriveUploader:
    """Upload videos to Google Drive."""

    SCOPES = ["https://www.googleapis.com/auth/drive.file"]

    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        self.folder_id = os.environ.get(
            "GOOGLE_DRIVE_FOLDER_ID",
            self.config["upload"]["google_drive"].get("folder_id", ""),
        )
        self.service = self._authenticate()

    def _authenticate(self):
        """Authenticate with Google Drive API."""
        creds_path = os.environ.get(
            "GOOGLE_CREDENTIALS_PATH",
            "credentials/service_account.json",
        )

        # Try service account first
        if os.path.exists(creds_path) and "service_account" in creds_path:
            creds = service_account.Credentials.from_service_account_file(
                creds_path, scopes=self.SCOPES
            )
        else:
            # OAuth2 flow
            token_path = "credentials/drive_token.json"
            creds = None
            if os.path.exists(token_path):
                creds = Credentials.from_authorized_user_file(token_path, self.SCOPES)
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        creds_path, self.SCOPES
                    )
                    creds = flow.run_local_server(port=0)
                with open(token_path, "w") as f:
                    f.write(creds.to_json())

        return build("drive", "v3", credentials=creds)

    def upload(self, file_path: str, title: str) -> str:
        """Upload a file to Google Drive and return the file URL."""
        file_metadata = {
            "name": title,
            "parents": [self.folder_id] if self.folder_id else [],
        }

        media = MediaFileUpload(
            file_path,
            mimetype="video/mp4",
            resumable=True,
        )

        file = self.service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, webViewLink",
        ).execute()

        file_id = file.get("id")
        link = file.get("webViewLink", f"https://drive.google.com/file/d/{file_id}")
        print(f"  ✅ Uploaded to Google Drive: {link}")
        return link


# ─── YouTube Uploader ──────────────────────────────────────────────

class YouTubeUploader:
    """Upload videos to YouTube as Shorts."""

    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        self.yt_config = self.config["upload"]["youtube"]
        self.service = self._authenticate()

    def _authenticate(self):
        """Authenticate with YouTube API."""
        client_secret_path = os.environ.get(
            "YOUTUBE_CLIENT_SECRET_PATH",
            "credentials/youtube_client_secret.json",
        )
        token_path = os.environ.get(
            "YOUTUBE_TOKEN_PATH",
            "credentials/youtube_token.json",
        )

        creds = None
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, self.SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    client_secret_path, self.SCOPES
                )
                creds = flow.run_local_server(port=0)
            with open(token_path, "w") as f:
                f.write(creds.to_json())

        return build("youtube", "v3", credentials=creds)

    def upload(
        self,
        file_path: str,
        title: str,
        description: str,
        tags: list[str],
        privacy: str = "public",
    ) -> str:
        """Upload video to YouTube."""
        # Add #Shorts to title for YouTube Shorts detection
        if "#Shorts" not in title:
            title = f"{title} #Shorts"

        # Ensure title is under 100 chars
        if len(title) > 100:
            title = title[:97] + "..."

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags + self.yt_config.get("default_tags", []),
                "categoryId": self.yt_config.get("category", "28"),
                "defaultLanguage": "uk",
                "defaultAudioLanguage": "uk",
            },
            "status": {
                "privacyStatus": privacy or self.yt_config.get("privacy", "public"),
                "selfDeclaredMadeForKids": False,
                "shortDescription": description[:500],
            },
        }

        media = MediaFileUpload(
            file_path,
            mimetype="video/mp4",
            resumable=True,
            chunksize=10 * 1024 * 1024,  # 10MB chunks
        )

        request = self.service.videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=media,
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"  📤 YouTube upload: {int(status.progress() * 100)}%")

        video_id = response["id"]
        url = f"https://youtube.com/shorts/{video_id}"
        print(f"  ✅ Uploaded to YouTube: {url}")
        return url


# ─── TikTok Uploader ──────────────────────────────────────────────

class TikTokUploader:
    """Upload videos to TikTok using Content Posting API."""

    BASE_URL = "https://open.tiktokapis.com/v2"

    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        self.access_token = os.environ.get("TIKTOK_ACCESS_TOKEN", "")
        self.tt_config = self.config["upload"]["tiktok"]

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def upload(
        self,
        file_path: str,
        title: str,
        description: str = "",
        hashtags: list[str] = None,
    ) -> str:
        """Upload video to TikTok using Content Posting API v2."""
        if not self.access_token:
            print("  ⚠️  TikTok: No access token, skipping upload")
            return ""

        file_size = os.path.getsize(file_path)

        # Step 1: Initialize upload
        init_body = {
            "post_info": {
                "title": title[:150],
                "privacy_level": self.tt_config.get(
                    "privacy_level", "PUBLIC_TO_EVERYONE"
                ),
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": file_size,
                "chunk_size": min(file_size, 10 * 1024 * 1024),
                "total_chunk_count": max(1, file_size // (10 * 1024 * 1024) + 1),
            },
        }

        resp = requests.post(
            f"{self.BASE_URL}/post/publish/inbox/video/init/",
            headers=self._headers(),
            json=init_body,
        )

        if resp.status_code != 200:
            print(f"  ❌ TikTok init failed: {resp.status_code} {resp.text}")
            return ""

        data = resp.json().get("data", {})
        publish_id = data.get("publish_id", "")
        upload_url = data.get("upload_url", "")

        if not upload_url:
            print(f"  ❌ TikTok: No upload URL received")
            return ""

        # Step 2: Upload video file
        with open(file_path, "rb") as f:
            upload_resp = requests.put(
                upload_url,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Range": f"bytes 0-{file_size - 1}/{file_size}",
                },
                data=f,
            )

        if upload_resp.status_code not in (200, 201):
            print(f"  ❌ TikTok upload failed: {upload_resp.status_code}")
            return ""

        # Step 3: Check publish status
        for attempt in range(10):
            time.sleep(5)
            status_resp = requests.post(
                f"{self.BASE_URL}/post/publish/status/fetch/",
                headers=self._headers(),
                json={"publish_id": publish_id},
            )
            status_data = status_resp.json().get("data", {})
            status = status_data.get("status", "")

            if status == "PUBLISH_COMPLETE":
                video_id = status_data.get("publicaly_available_post_id", [""])[0]
                url = f"https://www.tiktok.com/@homedomeua/video/{video_id}"
                print(f"  ✅ Published to TikTok: {url}")
                return url
            elif status in ("FAILED", "PUBLISH_FAILED"):
                print(f"  ❌ TikTok publish failed: {status_data}")
                return ""

            print(f"  ⏳ TikTok publish status: {status} (attempt {attempt+1}/10)")

        print("  ⚠️  TikTok: Publish timed out")
        return publish_id  # Return publish_id for manual check


# ─── Unified Uploader ─────────────────────────────────────────────

class ContentUploader:
    """Unified uploader that handles all platforms."""

    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        self.config_path = config_path
        self.results = {}

    def upload_all(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list[str],
        hashtags: list[str],
    ) -> dict:
        """Upload video to all enabled platforms."""
        upload_config = self.config["upload"]

        # Google Drive
        if upload_config.get("google_drive", {}).get("enabled", False):
            try:
                gdrive = GoogleDriveUploader(self.config_path)
                filename = f"{title.replace(' ', '_')[:50]}.mp4"
                self.results["google_drive"] = gdrive.upload(video_path, filename)
            except Exception as e:
                print(f"  ❌ Google Drive failed: {e}")
                self.results["google_drive"] = f"ERROR: {e}"

        # YouTube
        if upload_config.get("youtube", {}).get("enabled", False):
            try:
                yt = YouTubeUploader(self.config_path)
                # Build YouTube description with hashtags
                yt_desc = f"{description}\n\n{' '.join(hashtags)}\n\n🔋 homedome.com.ua"
                self.results["youtube"] = yt.upload(
                    file_path=video_path,
                    title=title,
                    description=yt_desc,
                    tags=tags,
                )
            except Exception as e:
                print(f"  ❌ YouTube failed: {e}")
                self.results["youtube"] = f"ERROR: {e}"

        # TikTok
        if upload_config.get("tiktok", {}).get("enabled", False):
            try:
                tt = TikTokUploader(self.config_path)
                # TikTok title includes hashtags
                tt_title = f"{title} {' '.join(hashtags[:5])}"
                self.results["tiktok"] = tt.upload(
                    file_path=video_path,
                    title=tt_title,
                    description=description,
                    hashtags=hashtags,
                )
            except Exception as e:
                print(f"  ❌ TikTok failed: {e}")
                self.results["tiktok"] = f"ERROR: {e}"

        return self.results


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    print("Upload module loaded. Configure credentials and use generate.py to run.")
