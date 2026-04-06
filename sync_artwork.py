#!/usr/bin/env python3
"""
Samsung Frame TV Artwork Sync Script
Syncs artwork from a local directory to multiple Samsung Frame TVs
"""

import asyncio
import json
import logging
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import List, Set, Dict, Optional, Any
import time
import hashlib
import datetime
import zoneinfo

from samsungtvws.async_art import SamsungTVAsyncArt
from samsungtvws.async_remote import SamsungTVWSAsyncRemote
from samsungtvws.remote import SendRemoteKey
from pysolar.solar import get_altitude

# Configure logging
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment variables with defaults
ARTWORK_DIR = os.getenv('ARTWORK_DIR', '/artwork')
TV_IPS = os.getenv('TV_IPS', '').split(',')
TV_IPS = [ip.strip() for ip in TV_IPS if ip.strip()]
SYNC_INTERVAL_MINUTES = int(os.getenv('SYNC_INTERVAL_MINUTES', '5'))
MATTE_STYLE = os.getenv('MATTE_STYLE', 'none')
TOKEN_DIR = os.getenv('TOKEN_DIR', '/tokens')

# Connection settings
TV_PORT = int(os.getenv('TV_PORT', '8001'))
TV_NAME = os.getenv('TV_NAME', 'Samsung TV')
TV_MAC = os.getenv('TV_MAC', '')  # Optional: used for Wake-on-LAN

# Optional slideshow override settings (if any are set, all are used with defaults)
SLIDESHOW_ENABLED = os.getenv('SLIDESHOW_ENABLED', '').lower() in ('true', '1', 'yes')
SLIDESHOW_INTERVAL = int(os.getenv('SLIDESHOW_INTERVAL', '15'))
SLIDESHOW_TYPE = os.getenv('SLIDESHOW_TYPE', 'shuffle').lower()
SLIDESHOW_OVERRIDE = os.getenv('SLIDESHOW_ENABLED') or os.getenv('SLIDESHOW_INTERVAL') or os.getenv('SLIDESHOW_TYPE')

# Optional brightness setting (0-50, where 50 is brightest)
BRIGHTNESS = os.getenv('BRIGHTNESS', '')
BRIGHTNESS = int(BRIGHTNESS) if BRIGHTNESS else None

# Optional solar-based brightness settings
SOLAR_BRIGHTNESS_ENABLED = os.getenv('SOLAR_BRIGHTNESS_ENABLED', '').lower() in ('true', '1', 'yes')
LOCATION_LATITUDE = float(os.getenv('LOCATION_LATITUDE', '0')) if os.getenv('LOCATION_LATITUDE') else None
LOCATION_LONGITUDE = float(os.getenv('LOCATION_LONGITUDE', '0')) if os.getenv('LOCATION_LONGITUDE') else None
LOCATION_TIMEZONE = os.getenv('LOCATION_TIMEZONE', 'UTC')
BRIGHTNESS_MIN = int(os.getenv('BRIGHTNESS_MIN', '2'))
BRIGHTNESS_MAX = int(os.getenv('BRIGHTNESS_MAX', '10'))

# Optional cleanup setting
REMOVE_UNKNOWN_IMAGES = os.getenv('REMOVE_UNKNOWN_IMAGES', '').lower() in ('true', '1', 'yes')

# Optional auto-off settings (turn off TVs at a specific time when in art mode)
AUTO_OFF_TIME = os.getenv('AUTO_OFF_TIME', '')  # 24-hour format, e.g., "22:00"
AUTO_OFF_GRACE_HOURS = float(os.getenv('AUTO_OFF_GRACE_HOURS', '2'))  # Hours after AUTO_OFF_TIME to keep trying

# Dry run mode (set by command line argument)
DRY_RUN = False

# Validate brightness range
if BRIGHTNESS_MIN >= BRIGHTNESS_MAX:
    logger.error(f"Invalid brightness range: BRIGHTNESS_MIN ({BRIGHTNESS_MIN}) must be less than BRIGHTNESS_MAX ({BRIGHTNESS_MAX}).")
    sys.exit(1)

# Supported image formats
SUPPORTED_FORMATS = {'.jpg', '.jpeg', '.png'}

# Timeout and delay constants (in seconds)
CONNECTION_TIMEOUT = 30.0
API_TIMEOUT = 10
UPLOAD_DELAY = 1.0
DELETE_DELAY = 0.5
UPLOAD_ATTEMPTS = 2


def is_within_auto_off_window() -> bool:
    """
    Check if the current time is within the auto-off window.

    The window starts at AUTO_OFF_TIME and extends for AUTO_OFF_GRACE_HOURS.
    Returns True if we should attempt to turn off TVs that are in art mode.
    """
    if not AUTO_OFF_TIME:
        return False

    try:
        # Parse the configured off time
        off_hour, off_minute = map(int, AUTO_OFF_TIME.split(':'))

        # Get current time in the configured timezone
        tz = zoneinfo.ZoneInfo(LOCATION_TIMEZONE)
        now = datetime.datetime.now(tz)

        # Create today's off time
        today_off_time = now.replace(hour=off_hour, minute=off_minute, second=0, microsecond=0)

        # Calculate the end of the grace period
        grace_end = today_off_time + datetime.timedelta(hours=AUTO_OFF_GRACE_HOURS)

        # Handle the case where the window spans midnight
        # If we're before today's off time, check if we're in yesterday's window
        if now < today_off_time:
            yesterday_off_time = today_off_time - datetime.timedelta(days=1)
            yesterday_grace_end = yesterday_off_time + datetime.timedelta(hours=AUTO_OFF_GRACE_HOURS)
            if yesterday_off_time <= now < yesterday_grace_end:
                logger.debug(f"Within auto-off window (from yesterday): {yesterday_off_time.strftime('%H:%M')} to {yesterday_grace_end.strftime('%H:%M')}")
                return True

        # Check if we're in today's window
        if today_off_time <= now < grace_end:
            logger.debug(f"Within auto-off window: {today_off_time.strftime('%H:%M')} to {grace_end.strftime('%H:%M')}")
            return True

        return False

    except Exception as e:
        logger.warning(f"Failed to check auto-off window: {e}")
        return False


def brightness_from_elevation(elevation: float) -> int:
    """
    Calculate brightness from sun elevation angle using atmospheric air mass model.

    This uses a physics-based approach that models how sunlight intensity changes
    as it passes through the atmosphere at different angles. The calculation is
    based on the air mass coefficient and Kasten-Young atmospheric attenuation formula.

    Args:
        elevation: Sun elevation angle in degrees (negative = below horizon)

    Returns:
        Brightness value between BRIGHTNESS_MIN and BRIGHTNESS_MAX
    """
    # If sun is at or below horizon, use minimum brightness
    if elevation <= 0:
        return BRIGHTNESS_MIN

    # Convert elevation to radians for calculation
    import math
    elevation_rad = math.radians(elevation)

    # Calculate air mass (AM) using Kasten-Young formula
    # This provides accurate results at all sun angles, especially near horizon
    # At zenith (90°): AM ≈ 1.0 (shortest path)
    # At 30° elevation: AM ≈ 2.0 (twice the atmosphere)
    air_mass = 1.0 / (math.sin(elevation_rad) + 0.50572 * (elevation + 6.07995)**(-1.6364))

    # Apply Kasten-Young atmospheric attenuation formula
    # Relative irradiance = 0.7^(AM^0.678)
    # This models how atmosphere absorbs/scatters sunlight
    # 0.7 represents typical clear-sky atmospheric transmittance
    relative_irradiance = 0.7 ** (air_mass ** 0.678)

    # Map relative irradiance (0.0 to 1.0) to brightness range
    brightness = BRIGHTNESS_MIN + int((BRIGHTNESS_MAX - BRIGHTNESS_MIN) * relative_irradiance)

    return brightness


def calculate_solar_brightness() -> Optional[int]:
    """
    Calculate brightness based on current sun position.
    Returns brightness value (min to max based on sun elevation angle).
    """
    if not SOLAR_BRIGHTNESS_ENABLED:
        return None

    if LOCATION_LATITUDE is None or LOCATION_LONGITUDE is None:
        logger.warning("Solar brightness enabled but LOCATION_LATITUDE or LOCATION_LONGITUDE not set")
        return None

    try:
        # Get current time in the specified timezone
        tz = zoneinfo.ZoneInfo(LOCATION_TIMEZONE)
        local_time = datetime.datetime.now(tz)
        utc_time = local_time.astimezone(datetime.timezone.utc)

        # Calculate sun elevation angle in degrees
        elevation = get_altitude(LOCATION_LATITUDE, LOCATION_LONGITUDE, utc_time)

        logger.debug(f"Sun elevation at {local_time.strftime('%Y-%m-%d %H:%M %Z')}: {elevation:.2f}°")

        # Calculate brightness from elevation
        brightness = brightness_from_elevation(elevation)

        if elevation <= 0:
            logger.info(f"Sun below horizon (elevation: {elevation:.2f}°), using minimum brightness: {brightness}")
        else:
            logger.info(f"Sun elevation: {elevation:.2f}° -> brightness: {brightness} "
                       f"(min: {BRIGHTNESS_MIN}, max: {BRIGHTNESS_MAX})")

        return brightness

    except Exception as e:
        logger.warning(f"Failed to calculate solar brightness: {e}")
        return None


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename by removing special characters.
    Keeps alphanumeric, spaces, hyphens, underscores, and the file extension dot.
    Collapses multiple spaces into one and strips leading/trailing spaces from the stem.
    """
    stem = Path(filename).stem
    ext = Path(filename).suffix.lower()
    # Keep only alphanumeric, spaces, hyphens, underscores
    stem = re.sub(r'[^a-zA-Z0-9 _-]', '', stem)
    # Collapse multiple spaces
    stem = re.sub(r' +', ' ', stem).strip()
    return f"{stem}{ext}" if stem else f"image{ext}"


class TVArtworkSync:
    """Manages artwork synchronization for a Samsung Frame TV"""

    def __init__(self, tv_ip: str) -> None:
        self.tv_ip = tv_ip
        self.tv = None
        self.token_file = Path(TOKEN_DIR) / f'tv_{tv_ip.replace(".", "_")}.txt'
        self.mapping_file = Path(TOKEN_DIR) / f'tv_{tv_ip.replace(".", "_")}_mapping.json'
        self.file_mapping: Dict[str, str] = {}  # filename -> content_id mapping
        self.model = "Unknown"
        self.version = "Unknown"
        self.active_port = TV_PORT
        self._load_mapping()

    def _load_mapping(self) -> None:
        """Load filename to content_id mapping from disk"""
        if self.mapping_file.exists():
            try:
                with open(self.mapping_file, 'r') as f:
                    self.file_mapping = json.load(f)
                logger.debug(f"Loaded mapping for TV {self.tv_ip}: {self.file_mapping}")
            except Exception as e:
                logger.warning(f"Failed to load mapping file: {e}")
                self.file_mapping = {}

    def _save_mapping(self) -> None:
        """Save filename to content_id mapping to disk"""
        try:
            self.mapping_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.mapping_file, 'w') as f:
                json.dump(self.file_mapping, f, indent=2)
            logger.debug(f"Saved mapping for TV {self.tv_ip}")
        except Exception as e:
            logger.warning(f"Failed to save mapping file: {e}")

    async def connect(self) -> bool:
        """Connect to the TV with automatic port fallback.
        
        Fallback logic:
        - If configured for port 8001 and it fails, try upgrading to 8002.
        - If configured for port 8002 and it fails, fall back to 8001 ONLY
          if a saved token already exists (from a prior 8002 handshake).
          Port 8001 without a token triggers Allow/Deny popups on 2024+ models.
        - If WoL is configured, wake the TV and retry before falling back.
        """
        try:
            # Ensure token directory exists
            self.token_file.parent.mkdir(parents=True, exist_ok=True)

            # --- Primary Connection Attempt ---
            connected = await self._try_connect(self.active_port)
            if connected:
                return True

            # --- Wake-on-LAN before fallback ---
            if TV_MAC:
                logger.info(f"Connection failed for {self.tv_ip}. Attempting Wake-on-LAN using {TV_MAC}...")
                await self._wake_on_lan()
                await asyncio.sleep(5)
                # Retry the configured port after waking
                if await self._try_connect(self.active_port):
                    return True

            # --- Automatic Fallback Logic ---
            if self.active_port == 8001:
                # Safe upgrade: 8001 -> 8002
                logger.info(f"Port 8001 connection failed for {self.tv_ip}. Attempting Port 8002 fallback...")
                connected = await self._try_connect(8002)
                if connected:
                    self.active_port = 8002
                    return True
            elif self.active_port == 8002 and self.token_file.exists():
                # Safe downgrade: 8002 -> 8001, but ONLY if we already have a saved token.
                # Without a token, 8001 would trigger an Allow/Deny popup on 2024+ models.
                logger.info(f"Port 8002 connection failed for {self.tv_ip}. Falling back to Port 8001 (token exists, popup safe)...")
                connected = await self._try_connect(8001)
                if connected:
                    # Don't permanently change active_port — keep trying 8002 first next cycle
                    return True

            logger.warning(f"Connection to TV at {self.tv_ip} failed on port {self.active_port} (TV may be off or disconnected)")
            return False

        except Exception as e:
            logger.warning(f"Failed to connect to TV at {self.tv_ip}: {e}")
            return False

    async def _try_connect(self, port: int) -> bool:
        """Helper to try a single connection with specific port"""
        try:
            self.tv = SamsungTVAsyncArt(
                host=self.tv_ip,
                port=port,
                name=TV_NAME,
                token_file=str(self.token_file),
                timeout=CONNECTION_TIMEOUT
            )
            # Test connection by getting available art
            await self.tv.available()
            
            # Fetch device info (Model/Version) for logs
            try:
                info = await self.tv.rest_device_info()
                if info and 'device' in info:
                    self.model = info['device'].get('modelName', 'Unknown')
                    self.version = info['device'].get('firmwareVersion', 'Unknown')
                    logger.info(f"Successfully connected to TV [{self.model}] at {self.tv_ip} (Port: {port}, Firmware: {self.version})")
                else:
                    logger.info(f"Successfully connected to TV at {self.tv_ip} (Port: {port})")
            except Exception:
                logger.info(f"Successfully connected to TV at {self.tv_ip} (Port: {port})")
                
            return True

        except (asyncio.TimeoutError, ConnectionRefusedError) as e:
            logger.debug(f"Connection to {self.tv_ip}:{port} failed: {type(e).__name__}: {e}")
            return False
        except Exception as e:
            logger.warning(f"Unexpected error connecting to {self.tv_ip}:{port}: {type(e).__name__}: {e}")
            return False
            
    async def _wake_on_lan(self) -> None:
        """Send a Wake-on-LAN magic packet to the TV's MAC address"""
        if not TV_MAC:
            return
            
        try:
            import socket
            import struct
            
            # Remove separators from MAC address
            mac_clean = re.sub(r'[^a-fA-F0-9]', '', TV_MAC)
            if len(mac_clean) != 12:
                logger.warning(f"Invalid MAC address for WoL: {TV_MAC}")
                return
                
            # Create magic packet
            data = bytes.fromhex('F' * 12 + mac_clean * 16)
            
            # Send to broadcast address
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                s.sendto(data, ('<broadcast>', 9))
                s.sendto(data, ('255.255.255.255', 9))
            logger.debug(f"Magic packet sent to {TV_MAC}")
            
        except Exception as e:
            logger.warning(f"Failed to send magic packet: {e}")

    async def is_in_art_mode(self) -> bool:
        """Check if the TV is currently in art mode (not being used for other content)"""
        try:
            # First check if TV is on
            is_on = await self.tv.on()
            if not is_on:
                # TV is off - safe to skip (will be synced when it turns on)
                logger.debug(f"TV {self.tv_ip} is powered off")
                return False

            # Check if TV is in art mode
            art_mode_status = await self.tv.get_artmode()
            is_art_mode = art_mode_status == 'on'

            logger.debug(f"TV {self.tv_ip} art mode status: {art_mode_status}")
            return is_art_mode

        except Exception as e:
            logger.debug(f"Could not determine art mode status for TV {self.tv_ip}: {e}")
            # If we can't determine the state, assume it's safe to sync
            # (this preserves backward-compatible behavior)
            return True

    async def get_local_images(self) -> Set[str]:
        """Get list of image files from local directory"""
        local_files = set()
        artwork_path = Path(ARTWORK_DIR)

        if not artwork_path.exists():
            logger.warning(f"Artwork directory does not exist: {ARTWORK_DIR}")
            return local_files

        for file_path in artwork_path.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_FORMATS:
                local_files.add(file_path.name)

        logger.info(f"Found {len(local_files)} images in {ARTWORK_DIR}")
        return local_files

    async def get_tv_images(self) -> tuple[Set[str], Set[str]]:
        """
        Get list of uploaded images on the TV.

        Returns:
            Tuple of (tracked_files, unknown_content_ids):
            - tracked_files: Set of filenames we've uploaded and are tracking
            - unknown_content_ids: Set of content_ids on TV that we don't recognize
        """
        try:
            # Get available images from "MY-C0002" category (My Photos/uploaded images only)
            available = await self.tv.available(category='MY-C0002')
            tv_content_ids = set()

            # Debug: log the raw response
            logger.debug(f"Available response: {available}")

            # The API returns a list directly, collect content_ids
            if available and isinstance(available, list):
                for item in available:
                    if 'content_id' in item:
                        tv_content_ids.add(item['content_id'])

            # Map content_ids back to filenames using our mapping
            tracked_files = set()
            unknown_content_ids = set()
            reverse_mapping = {v: k for k, v in self.file_mapping.items()}

            for content_id in tv_content_ids:
                if content_id in reverse_mapping:
                    tracked_files.add(reverse_mapping[content_id])
                else:
                    unknown_content_ids.add(content_id)

            logger.info(f"TV {self.tv_ip} has {len(tracked_files)} tracked images, {len(unknown_content_ids)} unknown images")
            return tracked_files, unknown_content_ids

        except Exception as e:
            logger.warning(f"Failed to get uploaded images from TV {self.tv_ip}: {e}")
            return set(), set()

    async def upload_image(self, file_path: Path) -> bool:
        """Upload a single image to the TV with retry logic.
        Uses a sanitized filename to avoid issues with special characters."""
        if DRY_RUN:
            logger.info(f"[DRY RUN] Would upload {file_path.name} to TV {self.tv_ip}")
            return True

        # Create a temp copy with a sanitized filename
        safe_name = sanitize_filename(file_path.name)
        use_temp = safe_name != file_path.name
        temp_dir = None

        try:
            if use_temp:
                temp_dir = tempfile.mkdtemp()
                upload_path = Path(temp_dir) / safe_name
                import shutil
                shutil.copy2(file_path, upload_path)
                logger.debug(f"Sanitized filename: {file_path.name} -> {safe_name}")
            else:
                upload_path = file_path

            for attempt in range(UPLOAD_ATTEMPTS):
                try:
                    if attempt > 0:
                        logger.info(f"Retrying upload of {file_path.name} to TV {self.tv_ip} (attempt {attempt + 1}/{UPLOAD_ATTEMPTS})")
                    else:
                        logger.info(f"Uploading {file_path.name} to TV {self.tv_ip}")

                    content_id = await self.tv.upload(
                        file=str(upload_path),
                        file_type='png' if file_path.suffix.lower() == '.png' else 'jpg',
                        matte=MATTE_STYLE if MATTE_STYLE != 'none' else None
                    )

                    if content_id:
                        # Save the mapping using the original filename as the key
                        self.file_mapping[file_path.name] = content_id
                        self._save_mapping()
                        logger.info(f"Successfully uploaded {file_path.name} to TV {self.tv_ip} (content_id: {content_id})")
                        return True
                    else:
                        logger.warning(f"Upload returned no content_id for {file_path.name} to TV {self.tv_ip}")
                        if attempt < UPLOAD_ATTEMPTS - 1:
                            await asyncio.sleep(UPLOAD_DELAY)
                        continue

                except Exception as e:
                    logger.warning(f"Error uploading {file_path.name} to TV {self.tv_ip}: {e}")
                    if attempt < UPLOAD_ATTEMPTS - 1:
                        await asyncio.sleep(UPLOAD_DELAY)
                    continue

            logger.warning(f"Failed to upload {file_path.name} to TV {self.tv_ip} after {UPLOAD_ATTEMPTS} attempts")
            return False

        finally:
            if temp_dir:
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)

    async def get_slideshow_settings(self) -> Optional[Dict[str, Any]]:
        """Get current slideshow settings from the TV"""
        try:
            logger.debug(f"Checking slideshow settings on TV {self.tv_ip}")

            get_result = await self.tv._send_art_request(
                {
                    "request": "get_slideshow_status"
                },
                timeout=API_TIMEOUT
            )

            if not get_result:
                logger.debug(f"Could not get slideshow status from TV {self.tv_ip}")
                return None

            # Parse the current settings
            current_value = get_result.get('value', 'off')
            current_type = get_result.get('type', 'shuffleslideshow')
            current_category = get_result.get('category_id', 'MY-C0002')

            logger.info(f"TV {self.tv_ip} slideshow settings: value={current_value}, type={current_type}, category={current_category}")

            # Return settings only if slideshow is enabled
            if current_value != 'off' and current_value:
                return {
                    'value': current_value,
                    'type': current_type if current_type else 'shuffleslideshow',
                    'category_id': current_category if current_category else 'MY-C0002'
                }
            else:
                logger.info(f"Slideshow is disabled on TV {self.tv_ip}")
                return None

        except Exception as e:
            logger.debug(f"Could not get slideshow settings from TV {self.tv_ip}: {e}")
            return None

    async def restart_slideshow(self, settings: Dict[str, Any]) -> bool:
        """Restart slideshow with given settings"""
        if DRY_RUN:
            logger.info(f"[DRY RUN] Would restart slideshow on TV {self.tv_ip} with {settings['value']} minutes")
            return True

        try:
            logger.info(f"Restarting slideshow on TV {self.tv_ip} with {settings['value']} minutes")

            set_result = await self.tv._send_art_request(
                {
                    "request": "set_slideshow_status",
                    "value": settings['value'],
                    "category_id": settings['category_id'],
                    "type": settings['type']
                },
                timeout=API_TIMEOUT
            )

            if set_result:
                logger.info(f"Successfully restarted slideshow on TV {self.tv_ip}")
                return True
            else:
                logger.debug(f"Slideshow restart returned no response on TV {self.tv_ip}")
                return False

        except Exception as e:
            logger.debug(f"Could not restart slideshow on TV {self.tv_ip}: {e}")
            return False

    async def set_brightness(self, brightness: int) -> bool:
        """Set brightness on the TV (0-50 range)"""
        if DRY_RUN:
            logger.info(f"[DRY RUN] Would set brightness to {brightness} on TV {self.tv_ip}")
            return True

        try:
            logger.info(f"Setting brightness to {brightness} on TV {self.tv_ip}")

            result = await self.tv.set_brightness(brightness)

            if result:
                logger.info(f"Successfully set brightness on TV {self.tv_ip}")
                return True
            else:
                logger.debug(f"Brightness setting returned no response on TV {self.tv_ip}")
                return False

        except Exception as e:
            logger.warning(f"Could not set brightness on TV {self.tv_ip}: {e}")
            return False

    async def turn_off(self) -> bool:
        """Turn off the TV via a separate remote control connection"""
        if DRY_RUN:
            logger.info(f"[DRY RUN] Would turn off TV {self.tv_ip}")
            return True

        try:
            logger.info(f"Turning off TV {self.tv_ip}")

            # The art API uses a different websocket endpoint and can't send
            # remote keys, so we need a separate remote control connection
            remote = SamsungTVWSAsyncRemote(
                host=self.tv_ip,
                port=8002,
                token_file=str(self.token_file),
                timeout=CONNECTION_TIMEOUT
            )
            try:
                # Frame TVs require holding the power button for 3 seconds to
                # actually power off. A single press just toggles art mode.
                await remote.send_commands(SendRemoteKey.hold("KEY_POWER", 3))
                logger.info(f"Successfully turned off TV {self.tv_ip}")
                return True
            finally:
                await remote.close()

        except Exception as e:
            logger.warning(f"Could not turn off TV {self.tv_ip}: {e}")
            return False

    async def sync(self, local_images: Set[str] = None) -> bool:
        """Synchronize artwork with the TV"""
        try:
            # Get local images if not provided
            if local_images is None:
                local_images = await self.get_local_images()

            # Get TV images (tracked and unknown)
            tv_images, unknown_images = await self.get_tv_images()

            # Determine what to upload and delete
            to_upload = local_images - tv_images
            to_delete = tv_images - local_images

            # Handle unknown images based on configuration
            if unknown_images:
                if REMOVE_UNKNOWN_IMAGES:
                    logger.info(f"TV {self.tv_ip}: Found {len(unknown_images)} unknown images, will remove them (REMOVE_UNKNOWN_IMAGES=true)")
                else:
                    logger.warning(f"TV {self.tv_ip}: Found {len(unknown_images)} unknown images on TV that are not in the artwork folder. "
                                 f"Set REMOVE_UNKNOWN_IMAGES=true to remove them. Content IDs: {', '.join(sorted(unknown_images))}")

            logger.info(f"TV {self.tv_ip} sync: {len(to_upload)} to upload, {len(to_delete)} tracked to delete{f', {len(unknown_images)} unknown to delete' if REMOVE_UNKNOWN_IMAGES and unknown_images else ''}")

            # Determine desired slideshow settings from environment (checked every sync run)
            desired_slideshow_settings = None
            if SLIDESHOW_OVERRIDE and SLIDESHOW_ENABLED:
                slideshow_type = 'shuffleslideshow' if SLIDESHOW_TYPE == 'shuffle' else 'slideshow'
                desired_slideshow_settings = {
                    'value': str(SLIDESHOW_INTERVAL),
                    'type': slideshow_type,
                    'category_id': 'MY-C0002'
                }

            # For image changes without override, we need to preserve TV's current settings
            preserve_slideshow_settings = None
            if (to_upload or to_delete or (REMOVE_UNKNOWN_IMAGES and unknown_images)) and local_images:
                if not SLIDESHOW_OVERRIDE:
                    # Preserve TV's current slideshow settings to restore after image changes
                    preserve_slideshow_settings = await self.get_slideshow_settings()

            # Determine brightness to apply (every sync run, regardless of image changes)
            brightness_to_apply = None

            # Solar brightness takes precedence over manual brightness
            solar_brightness = calculate_solar_brightness()
            if solar_brightness is not None:
                brightness_to_apply = solar_brightness
            elif BRIGHTNESS is not None:
                brightness_to_apply = BRIGHTNESS
                logger.info(f"Using manual brightness override: {BRIGHTNESS}")

            # Upload new images
            for filename in to_upload:
                file_path = Path(ARTWORK_DIR) / filename
                await self.upload_image(file_path)
                # Small delay between uploads to avoid overwhelming the TV
                await asyncio.sleep(UPLOAD_DELAY)

            # Delete removed images (batch delete for efficiency)
            if to_delete:
                content_ids_to_delete = [self.file_mapping.get(filename) for filename in to_delete]
                content_ids_to_delete = [cid for cid in content_ids_to_delete if cid]  # Filter out None values

                if content_ids_to_delete:
                    if DRY_RUN:
                        logger.info(f"[DRY RUN] Would delete {len(content_ids_to_delete)} tracked images from TV {self.tv_ip}: {', '.join(to_delete)}")
                    else:
                        logger.info(f"Deleting {len(content_ids_to_delete)} tracked images from TV {self.tv_ip}")
                        try:
                            await self.tv.delete_list(content_ids_to_delete)
                            # Remove from mapping
                            for filename in to_delete:
                                if filename in self.file_mapping:
                                    del self.file_mapping[filename]
                            self._save_mapping()
                            logger.info(f"Successfully deleted {len(content_ids_to_delete)} tracked images from TV {self.tv_ip}")
                        except Exception as e:
                            logger.warning(f"Error batch deleting tracked images from TV {self.tv_ip}: {e}")

            # Delete unknown images if configured (batch delete for efficiency)
            if REMOVE_UNKNOWN_IMAGES and unknown_images:
                if DRY_RUN:
                    logger.info(f"[DRY RUN] Would delete {len(unknown_images)} unknown images from TV {self.tv_ip}")
                else:
                    logger.info(f"Deleting {len(unknown_images)} unknown images from TV {self.tv_ip}")
                    try:
                        await self.tv.delete_list(list(unknown_images))
                        logger.info(f"Successfully deleted {len(unknown_images)} unknown images from TV {self.tv_ip}")
                    except Exception as e:
                        logger.warning(f"Error batch deleting unknown images from TV {self.tv_ip}: {e}")

            # If we made changes and have images, select an image and restore preserved slideshow
            if local_images and (to_upload or to_delete or (REMOVE_UNKNOWN_IMAGES and unknown_images)):
                # Verify file_mapping against what's actually on the TV now
                verified_mapping = {}
                try:
                    current_on_tv, _ = await self.get_tv_images()
                    verified_mapping = {k: v for k, v in self.file_mapping.items() if k in current_on_tv}
                except Exception as e:
                    logger.debug(f"Could not verify TV images for selection on {self.tv_ip}: {e}")
                    verified_mapping = self.file_mapping

                if verified_mapping:
                    try:
                        # Pick random image if shuffle mode, otherwise pick first
                        import random
                        # Use desired settings if available, otherwise preserved settings for shuffle check
                        settings_for_mode = desired_slideshow_settings or preserve_slideshow_settings
                        if settings_for_mode and settings_for_mode.get('type') == 'shuffleslideshow':
                            content_id = random.choice(list(verified_mapping.values()))
                            if DRY_RUN:
                                logger.info(f"[DRY RUN] Would select random image on TV {self.tv_ip} for shuffle mode")
                            else:
                                logger.info(f"Selecting random image on TV {self.tv_ip} for shuffle mode")
                        else:
                            content_id = list(verified_mapping.values())[0]
                            if DRY_RUN:
                                logger.info(f"[DRY RUN] Would select first image on TV {self.tv_ip} to prevent default art")
                            else:
                                logger.info(f"Selecting first image on TV {self.tv_ip} to prevent default art")

                        if not DRY_RUN:
                            await self.tv.select_image(content_id, show=True)

                        # Restore preserved slideshow settings (when no override is set)
                        if preserve_slideshow_settings:
                            await self.restart_slideshow(preserve_slideshow_settings)

                    except Exception as e:
                        logger.warning(f"Failed to select image on TV {self.tv_ip}: {e}")
                else:
                    logger.warning(f"No verified images available on TV {self.tv_ip} to select, skipping image selection")

            # Apply slideshow settings every sync run if override is set (compare with current to avoid unnecessary updates)
            if desired_slideshow_settings:
                try:
                    current_settings = await self.get_slideshow_settings()
                    # Check if settings differ (compare value and type)
                    needs_update = (
                        not current_settings or
                        current_settings.get('value') != desired_slideshow_settings['value'] or
                        current_settings.get('type') != desired_slideshow_settings['type']
                    )
                    if needs_update:
                        logger.info(f"Slideshow settings changed, updating TV {self.tv_ip}: {desired_slideshow_settings['value']} min, {desired_slideshow_settings['type']}")
                        await self.restart_slideshow(desired_slideshow_settings)
                    else:
                        logger.info(f"Slideshow settings unchanged on TV {self.tv_ip}")
                except Exception as e:
                    logger.warning(f"Failed to update slideshow settings on TV {self.tv_ip}: {e}")

            # Apply brightness every sync run (not just when images change)
            if brightness_to_apply is not None:
                try:
                    await self.set_brightness(brightness_to_apply)
                except Exception as e:
                    logger.warning(f"Failed to set brightness on TV {self.tv_ip}: {e}")

            logger.info(f"Sync completed for TV {self.tv_ip}")
            return True

        except Exception as e:
            logger.warning(f"Error during sync for TV {self.tv_ip}: {e}")
            return False

    async def close(self) -> None:
        """Close connection to TV"""
        if self.tv:
            try:
                await self.tv.close()
            except Exception:
                pass


async def sync_all_tvs() -> None:
    """Synchronize artwork to all configured TVs"""
    if not TV_IPS:
        logger.error("No TV IPs configured. Set TV_IPS environment variable.")
        return

    logger.info(f"Starting sync for {len(TV_IPS)} TV(s): {', '.join(TV_IPS)}")

    # Create sync objects for each TV
    tv_syncs = [TVArtworkSync(ip) for ip in TV_IPS]

    # Try to connect to each TV
    connected_tvs = []
    for tv_sync in tv_syncs:
        if await tv_sync.connect():
            connected_tvs.append(tv_sync)

    if not connected_tvs:
        logger.warning("No TVs are currently available")
        return

    # Filter out TVs that are not in art mode (e.g., watching HDMI content)
    tvs_to_sync = []
    for tv_sync in connected_tvs:
        if await tv_sync.is_in_art_mode():
            tvs_to_sync.append(tv_sync)
        else:
            logger.info(f"Skipping TV {tv_sync.tv_ip} - not in art mode (may be in use)")

    if not tvs_to_sync:
        logger.info("No TVs in art mode to sync")
        # Close all connections
        await asyncio.gather(*[tv.close() for tv in tv_syncs])
        return

    # Get local images once (shared by all TVs)
    logger.info(f"Syncing {len(tvs_to_sync)} TV(s) in art mode")
    local_images = await tvs_to_sync[0].get_local_images() if tvs_to_sync else set()

    # Sync all TVs that are in art mode with the same local images
    await asyncio.gather(*[tv.sync(local_images) for tv in tvs_to_sync])

    # Check if we should turn off TVs (auto-off feature)
    if is_within_auto_off_window():
        grace_display = int(AUTO_OFF_GRACE_HOURS) if AUTO_OFF_GRACE_HOURS == int(AUTO_OFF_GRACE_HOURS) else AUTO_OFF_GRACE_HOURS
        logger.info(f"Within auto-off window ({AUTO_OFF_TIME} + {grace_display}h grace), turning off TVs in art mode")
        for tv_sync in tvs_to_sync:
            await tv_sync.turn_off()

    # Close all connections
    await asyncio.gather(*[tv.close() for tv in tv_syncs])

    logger.info("Sync cycle completed")


async def main() -> None:
    """Main loop - sync periodically"""
    logger.info("=" * 60)
    logger.info("Samsung Frame TV Artwork Sync Service")
    logger.info("=" * 60)
    logger.info(f"Artwork directory: {ARTWORK_DIR}")
    logger.info(f"TV IPs: {', '.join(TV_IPS) if TV_IPS else 'None configured'}")
    logger.info(f"Sync interval: {SYNC_INTERVAL_MINUTES} minutes")
    logger.info(f"Matte style: {MATTE_STYLE}")
    logger.info("=" * 60)

    if not TV_IPS:
        logger.error("No TV IPs configured. Exiting.")
        sys.exit(1)

    sync_interval_seconds = SYNC_INTERVAL_MINUTES * 60

    while True:
        try:
            await sync_all_tvs()
        except Exception as e:
            logger.error(f"Error in sync cycle: {e}", exc_info=True)

        logger.info(f"Waiting {SYNC_INTERVAL_MINUTES} minutes until next sync...")
        await asyncio.sleep(sync_interval_seconds)


if __name__ == '__main__':
    # Check for command-line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == '--test-solar':
            # Run solar brightness test mode
            if LOCATION_LATITUDE is None or LOCATION_LONGITUDE is None:
                from solar_test_output import print_test_error
                print_test_error("Location not configured")
                sys.exit(1)

            from solar_test_output import run_solar_brightness_test

            # Use the actual brightness calculation function
            run_solar_brightness_test(
                LOCATION_LATITUDE,
                LOCATION_LONGITUDE,
                LOCATION_TIMEZONE,
                BRIGHTNESS_MIN,
                BRIGHTNESS_MAX,
                brightness_from_elevation
            )
            sys.exit(0)
        elif sys.argv[1] == '--dry-run':
            # Enable dry run mode
            DRY_RUN = True
            logger.info("=" * 60)
            logger.info("DRY RUN MODE - No changes will be made to TVs")
            logger.info("=" * 60)

    # Normal operation mode
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        sys.exit(0)
