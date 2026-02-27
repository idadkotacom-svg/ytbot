"""
Scheduler module — manages the upload queue with timed viral hour uploads.
Uploads videos at scheduled times (default: 21:00, 00:00, 03:00 WIB)
targeting US/EU peak hours. Max 3 uploads per day.
"""
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.core import config
from src.api.drive import DriveUploader
from src.api.youtube import YouTubeUploader, QuotaExceededError

logger = logging.getLogger(__name__)

WIB = timezone(timedelta(hours=7))


class Scheduler:
    """Manages the video upload queue with viral hour scheduling."""

    def __init__(self):
        # We dynamically load sheets to avoid circular imports if needed
        from src.api.sheets import SheetsManager
        self.sheets = SheetsManager()
        self.drive = DriveUploader()
        self._youtube_cache = {}  # channel_name -> YouTubeUploader
        self.temp_dir = config.TEMP_DIR

    def _get_youtube(self, channel_name: str = None) -> YouTubeUploader:
        """Get or create YouTube uploader for a specific channel."""
        channel = channel_name or config.DEFAULT_CHANNEL
        if channel not in self._youtube_cache:
            self._youtube_cache[channel] = YouTubeUploader(channel)
        return self._youtube_cache[channel]
        
    def is_upload_time(self) -> bool:
        """
        Check if current time is within a scheduled upload window.
        Returns True if we're within ±5 minutes of a scheduled time.
        """
        now = datetime.now(WIB)
        current_minutes = now.hour * 60 + now.minute

        for time_str in config.UPLOAD_SCHEDULE_HOURS:
            try:
                h, m = map(int, time_str.split(":"))
                scheduled_minutes = h * 60 + m

                # Check if within ±30 minute window to prevent stuck pending videos
                diff = abs(current_minutes - scheduled_minutes)
                # Handle midnight wrap (e.g., 23:58 vs 00:00)
                if diff > 720:  # more than 12 hours
                    diff = 1440 - diff

                if diff <= 30:
                    return True
            except (ValueError, AttributeError):
                continue

        return False

    def get_next_upload_time(self) -> str:
        """Get the next scheduled upload time as a string."""
        now = datetime.now(WIB)
        current_minutes = now.hour * 60 + now.minute

        upcoming = []
        for time_str in config.UPLOAD_SCHEDULE_HOURS:
            try:
                h, m = map(int, time_str.split(":"))
                scheduled_minutes = h * 60 + m
                diff = scheduled_minutes - current_minutes
                if diff < 0:
                    diff += 1440  # next day
                upcoming.append((diff, time_str))
            except (ValueError, AttributeError):
                continue

        if upcoming:
            upcoming.sort()
            return upcoming[0][1] + " WIB"
        return "N/A"

    def process_queue(self) -> list[dict]:
        """
        Process the upload queue for YouTube.
        It uploads immediately up to daily limit and schedules natively.
        """
        results = []
        
        # YouTube: Process immediately, ignoring local schedule time
        logger.info("Processing YouTube natively-scheduled queue...")
        results.extend(self._process_platform_queue(force=True))
            
        return results

    def force_upload(self) -> list[dict]:
        """Manually trigger upload bypassing time checks."""
        logger.info("Force upload triggered...")
        return self._process_platform_queue(force=True)

    def _process_platform_queue(self, force: bool = False) -> list[dict]:
        """Process the upload queue for YouTube."""
        today = datetime.now(WIB).strftime("%Y-%m-%d")

        uploads_today = self.sheets.count_uploads_today()
        remaining = config.MAX_UPLOADS_PER_DAY_YOUTUBE - uploads_today

        logger.info(
            f"Queue check youtube — Uploads today: {uploads_today}/"
            f"{config.MAX_UPLOADS_PER_DAY_YOUTUBE}, Remaining: {remaining}"
        )

        if remaining <= 0:
            logger.info("Daily upload limit reached for youtube.")
            return []

        # Get videos to process (scheduled for today first, then pending)
        scheduled = self.sheets.get_scheduled_videos(today)
        pending = self.sheets.get_pending_videos()
        to_process = scheduled + pending

        if not to_process:
            logger.info("No videos to process for youtube.")
            return []

        results = []
        
        # YouTube always tries to process all remaining slots.
        limit = remaining
        
        for video in to_process[:limit]:
            result = self._process_single(video)
            results.append(result)

            # Stop entire batch immediately if YouTube quota is exhausted
            if result.get("quota_exceeded"):
                logger.warning("YouTube quota exhausted — stopping batch.")
                break
            
            # Decrement remaining regardless of success to prevent infinite failing loops
            # especially when API quotas are hit.
            remaining -= 1
            if remaining <= 0:
                break

        return results

    def _process_single(self, video_data: dict) -> dict:
        """Process a single video upload for YouTube."""
        row = video_data["row"]
        filename = video_data["filename"]
        drive_link = video_data["drive_link"]
        title = video_data["title"]
        desc = video_data["description"]
        tags = video_data["tags"]
        channel_name = video_data.get("channel", config.DEFAULT_CHANNEL)

        # For YouTube Native Scheduling, convert WIB scheduled time back to UTC ISO
        sched_date_str = video_data.get("scheduled_date", "")
        publish_at_iso = None
        if sched_date_str:
            try:
                # E.g. "2026-03-01 21:00 WIB"
                dt_str = sched_date_str.replace(" WIB", "")
                dt_wib = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                # Attach timezone info (WIB is UTC+7)
                dt_wib = dt_wib.replace(tzinfo=WIB)
                publish_at_iso = dt_wib.astimezone(timezone.utc).isoformat()
            except ValueError:
                logger.warning(f"Could not parse scheduled_date '{sched_date_str}' for ISO conversion.")

        # Update description with tags
        if isinstance(tags, list):
            tags_list = [t.strip().replace("#", "") for t in tags if t.strip()]
        else:
            tags_list = [t.strip().replace("#", "") for t in tags.split(",") if t.strip()]
            if not tags_list:
                tags_list = [t.strip().replace("#", "") for t in tags.split() if t.strip()]
        
        hashtag_str = " ".join([f"#{t.replace(' ', '')}" for t in tags_list])
        full_desc = f"{desc}\n\n{hashtag_str}" if hashtag_str else desc

        logger.info(f"Processing row {row} on youtube: '{filename}'")
        self.sheets.update_status(row, "uploading")

        local_path = None
        try:
            # 1. Download from Google Drive
            file_id = self._extract_drive_id(drive_link)
            if not file_id:
                raise ValueError("Gagal ekstrak File ID dari Google Drive link")

            logger.info(f"Downloading from Drive: {file_id}")
            local_path = self.drive.download(file_id, filename)

            # 2. Extract final title & tags
            clean_title = title.split("|")[0].strip() if "|" in title else title
            
            if isinstance(tags, list):
                tags_list = [t.strip().replace("#", "") for t in tags if t.strip()]
            else:
                tags_list = [t.strip().replace("#", "") for t in tags.split() if t.strip()]

            if not os.path.exists(local_path):
                raise FileNotFoundError(f"File tidak ditemukan setelah download: {local_path}")

            # 3. Upload to YouTube
            logger.info(f"Uploading to YouTube ({channel_name}): '{clean_title}'...")
            yt_client = self._get_youtube(channel_name)
            
            video_url = yt_client.upload(
                file_path=local_path,
                title=clean_title,
                description=full_desc,
                tags=tags_list,
                publish_at=publish_at_iso
            )

            # 4. Save to Sheets
            self.sheets.set_youtube_link(row, video_url)
            
            # Do NOT update the scheduled_date to generic `today` anymore 
            # since Youtube native scheduling actually relies on that exact value being retained.

            return {
                "success": True,
                "row": row,
                "filename": filename,
                "youtube_link": video_url,
            }

        except QuotaExceededError as e:
            logger.warning(f"Quota exceeded on row {row}: {e}")
            # Mark back to pending so it retries when quota resets
            self.sheets.update_status(row, "pending")
            return {
                "success": False,
                "quota_exceeded": True,
                "row": row,
                "filename": filename,
                "error": str(e),
            }
        except Exception as e:
            logger.error(f"Failed to process row {row}: {e}")
            self.sheets.update_status(row, "failed")
            return {
                "success": False,
                "row": row,
                "filename": filename,
                "error": str(e),
            }
        finally:
            if local_path and os.path.exists(local_path):
                try:
                    os.remove(local_path)
                    logger.info(f"Cleaned up temp file: {local_path}")
                except Exception as e:
                    logger.warning(f"Could not remove temp file {local_path}: {e}")

    def _schedule_remaining(self, date_str: str):
        """Schedule all remaining pending videos for a future date."""
        pending = self.sheets.get_pending_videos()
        for video in pending:
            self.sheets.set_scheduled_date(video["row"], date_str)
            logger.info(
                f"Scheduled '{video['filename']}' for {date_str} on youtube"
            )

    @staticmethod
    def _extract_drive_id(drive_link: str) -> str:
        """Extract file ID from a Google Drive link."""
        if not drive_link:
            return ""

        # Handle various Drive link formats
        if "/file/d/" in drive_link:
            parts = drive_link.split("/file/d/")[1]
            return parts.split("/")[0].split("?")[0]

        if "id=" in drive_link:
            return drive_link.split("id=")[1].split("&")[0]

        return drive_link.strip()

    def get_status_message(self) -> str:
        """Generate a human-readable status message for YouTube."""
        yt_summary = self.sheets.get_queue_summary()
        
        next_time = self.get_next_upload_time()
        is_upload = self.is_upload_time()

        schedule_str = " → ".join(config.UPLOAD_SCHEDULE_HOURS)
        now_str = datetime.now(WIB).strftime("%H:%M WIB")

        msg = (
            "📊 **Upload Queue Status**\n\n"
            f"📺 <b>YouTube</b>:\n"
            f"📹 Total: {yt_summary['total']} | ⏳ Pending: {yt_summary['pending']} | 📅 Scheduled: {yt_summary['scheduled']}\n"
            f"📤 Uploads today: {yt_summary['uploads_today']}/{config.MAX_UPLOADS_PER_DAY_YOUTUBE}\n\n"
            f"🕐 Schedule: `{schedule_str}` WIB\n"
            f"⏰ Now: {now_str}\n"
            f"⏭️ Next upload: {next_time}\n"
            f"{'🟢 Upload window ACTIVE' if is_upload else '🔴 Waiting for next window'}"
        )

        return msg
