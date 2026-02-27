"""
YouTube upload module — uploads videos to YouTube via Data API v3.
Supports multiple channels with separate OAuth2 tokens.
"""
import logging
import os
from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request

from src.core import config

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def get_auth_url(channel_name: str) -> tuple[str, InstalledAppFlow]:
    """Generate authorization URL for a specific channel."""
    secrets_file = config.get_channel_client_secrets_file(channel_name)
    if not os.path.exists(secrets_file):
        raise FileNotFoundError(f"Missing client_secrets file for channel '{channel_name}'")
    
    flow = InstalledAppFlow.from_client_secrets_file(secrets_file, SCOPES)
    flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
    auth_url, _ = flow.authorization_url(prompt='consent')
    return auth_url, flow


def save_auth_code(channel_name: str, code: str, flow: InstalledAppFlow) -> bool:
    """Exchange authorization code for credentials and save them to a file."""
    try:
        flow.fetch_token(code=code)
        creds = flow.credentials
        token_file = config.get_channel_token_file(channel_name)
        with open(token_file, "w") as f:
            f.write(creds.to_json())
        logger.info(f"Successfully saved new YouTube token for '{channel_name}'.")
        return True
    except Exception as e:
        logger.error(f"Failed to exchange auth code for '{channel_name}': {e}")
        return False


class QuotaExceededError(Exception):
    """Raised when YouTube API daily upload quota is exhausted (HTTP 403)."""
    pass


class YouTubeUploader:
    """Handles uploading videos to YouTube via the Data API v3."""

    def __init__(self, channel_name: str = None):
        """
        Initialize uploader for a specific channel.

        Args:
            channel_name: Channel name (must match one in YOUTUBE_CHANNELS).
                          If None, uses the default channel.
        """
        self.channel_name = channel_name or config.DEFAULT_CHANNEL
        self.token_file = config.get_channel_token_file(self.channel_name)
        self.creds = self._authenticate()

    def _authenticate(self) -> Credentials:
        """Authenticate with YouTube using OAuth2."""
        creds = None

        # Load existing token
        if os.path.exists(self.token_file):
            creds = Credentials.from_authorized_user_file(self.token_file, SCOPES)

        # Refresh or get new token
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info(f"Refreshing YouTube token for '{self.channel_name}'...")
                creds.refresh(Request())
            else:
                logger.info(
                    f"Starting YouTube OAuth2 flow for '{self.channel_name}'...\n"
                )
                secrets_file = config.get_channel_client_secrets_file(self.channel_name)
                flow = InstalledAppFlow.from_client_secrets_file(
                    secrets_file, SCOPES
                )
                
                # Check if running on Render (headless server)
                if os.environ.get("RENDER"):
                    raise ValueError(
                        f"Missing YouTube token for '{self.channel_name}'. "
                        f"Please run /login in Telegram to authenticate."
                    )
                else:
                    logger.info("Detected Local environment — using Local Server OAuth flow.")
                    creds = flow.run_local_server(port=0, open_browser=False)

            # Save token for future use
            with open(self.token_file, "w") as f:
                f.write(creds.to_json())
            logger.info(f"YouTube token saved for '{self.channel_name}'.")

        return creds

    def upload(
        self,
        file_path: str,
        title: str,
        description: str = "",
        tags: str = "",
        category: str = None,
        privacy: str = None,
        publish_at: str = None,
    ) -> dict:
        """
        Upload a video to YouTube.

        Returns:
            dict with keys: video_id, youtube_link
        """
        if category is None:
            category = config.YOUTUBE_CATEGORY
        if privacy is None:
            privacy = config.YOUTUBE_PRIVACY

        if isinstance(tags, list):
            tag_list = [t.strip() for t in tags if t.strip()]
        else:
            tag_list = [t.strip() for t in tags.split(",") if t.strip()]

        body = {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "tags": tag_list,
                "categoryId": category,
            },
            "status": {
                "privacyStatus": "private" if publish_at else (privacy or config.YOUTUBE_PRIVACY),
                "selfDeclaredMadeForKids": False,
            },
        }

        if publish_at:
            body["status"]["publishAt"] = publish_at

        media = MediaFileUpload(
            file_path,
            mimetype="video/mp4",
            resumable=True,
            chunksize=10 * 1024 * 1024,
        )

        logger.info(f"Uploading to YouTube ({self.channel_name}): '{title}'...")

        # Build service dynamically for this thread
        service = build("youtube", "v3", credentials=self.creds)

        request = service.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        response = None
        try:
            while response is None:
                status, response = request.next_chunk()
                if status:
                    progress = int(status.progress() * 100)
                    logger.info(f"YouTube upload progress: {progress}%")
        except HttpError as e:
            # Detect quota exceeded (HTTP 403 with reason quotaExceeded or forbidden)
            # OR channel limit exceeded (HTTP 400 with reason uploadLimitExceeded)
            reason = ""
            if hasattr(e, "error_details") and e.error_details:
                reason = e.error_details[0].get("reason", "")
            
            is_quota = (e.resp.status == 403 and reason in ("quotaExceeded", "forbidden", ""))
            is_channel_limit = (e.resp.status == 400 and reason == "uploadLimitExceeded")
            
            if is_quota or is_channel_limit:
                limit_type = "Channel Upload Limit" if is_channel_limit else "API Quota"
                raise QuotaExceededError(
                    f"YouTube {limit_type} habis (HTTP {e.resp.status}). "
                    f"Quota reset harian. Detail: {e}"
                ) from e
            raise  # Re-raise other HTTP errors normally

        video_id = response["id"]
        youtube_link = f"https://youtu.be/{video_id}"

        logger.info(f"Upload complete ({self.channel_name}): {youtube_link}")

        return {
            "video_id": video_id,
            "youtube_link": youtube_link,
        }
