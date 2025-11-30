#!/usr/bin/env python3
"""
Samsung Frame TV Artwork Sync Script
Syncs artwork from a local directory to multiple Samsung Frame TVs
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import List, Set, Dict, Optional, Any
import time
import hashlib

from samsungtvws.async_art import SamsungTVAsyncArt

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

# Supported image formats
SUPPORTED_FORMATS = {'.jpg', '.jpeg', '.png'}

# Timeout and delay constants (in seconds)
CONNECTION_TIMEOUT = 10.0
API_TIMEOUT = 10
UPLOAD_DELAY = 1.0
DELETE_DELAY = 0.5


class TVArtworkSync:
    """Manages artwork synchronization for a Samsung Frame TV"""

    def __init__(self, tv_ip: str):
        self.tv_ip = tv_ip
        self.tv = None
        self.token_file = Path(TOKEN_DIR) / f'tv_{tv_ip.replace(".", "_")}.txt'
        self.mapping_file = Path(TOKEN_DIR) / f'tv_{tv_ip.replace(".", "_")}_mapping.json'
        self.file_mapping: Dict[str, str] = {}  # filename -> content_id mapping
        self._load_mapping()

    def _load_mapping(self):
        """Load filename to content_id mapping from disk"""
        if self.mapping_file.exists():
            try:
                with open(self.mapping_file, 'r') as f:
                    self.file_mapping = json.load(f)
                logger.debug(f"Loaded mapping for TV {self.tv_ip}: {self.file_mapping}")
            except Exception as e:
                logger.warning(f"Failed to load mapping file: {e}")
                self.file_mapping = {}

    def _save_mapping(self):
        """Save filename to content_id mapping to disk"""
        try:
            self.mapping_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.mapping_file, 'w') as f:
                json.dump(self.file_mapping, f, indent=2)
            logger.debug(f"Saved mapping for TV {self.tv_ip}")
        except Exception as e:
            logger.warning(f"Failed to save mapping file: {e}")

    async def connect(self) -> bool:
        """Connect to the TV"""
        try:
            # Ensure token directory exists
            self.token_file.parent.mkdir(parents=True, exist_ok=True)

            # Create TV connection with timeout parameter
            self.tv = SamsungTVAsyncArt(
                host=self.tv_ip,
                port=8002,
                token_file=str(self.token_file),
                timeout=CONNECTION_TIMEOUT
            )

            # Test connection by getting available art
            await self.tv.available()
            logger.info(f"Successfully connected to TV at {self.tv_ip}")
            return True

        except asyncio.TimeoutError:
            logger.warning(f"Connection to TV at {self.tv_ip} timed out (TV may be off)")
            return False
        except Exception as e:
            logger.warning(f"Failed to connect to TV at {self.tv_ip}: {e}")
            return False

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

    async def get_tv_images(self) -> Set[str]:
        """Get list of uploaded images on the TV using our mapping"""
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
            tv_files = set()
            reverse_mapping = {v: k for k, v in self.file_mapping.items()}
            for content_id in tv_content_ids:
                if content_id in reverse_mapping:
                    tv_files.add(reverse_mapping[content_id])

            logger.info(f"TV {self.tv_ip} has {len(tv_files)} tracked uploaded images")
            return tv_files

        except Exception as e:
            logger.warning(f"Failed to get uploaded images from TV {self.tv_ip}: {e}")
            return set()

    async def upload_image(self, file_path: Path) -> bool:
        """Upload a single image to the TV"""
        try:
            logger.info(f"Uploading {file_path.name} to TV {self.tv_ip}")

            content_id = await self.tv.upload(
                file=str(file_path),
                file_type='png' if file_path.suffix.lower() == '.png' else 'jpg',
                matte=MATTE_STYLE if MATTE_STYLE != 'none' else None
            )

            if content_id:
                # Save the mapping
                self.file_mapping[file_path.name] = content_id
                self._save_mapping()
                logger.info(f"Successfully uploaded {file_path.name} to TV {self.tv_ip} (content_id: {content_id})")
                return True
            else:
                logger.warning(f"Failed to upload {file_path.name} to TV {self.tv_ip}")
                return False

        except Exception as e:
            logger.warning(f"Error uploading {file_path.name} to TV {self.tv_ip}: {e}")
            return False

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

    async def delete_image(self, filename: str) -> bool:
        """Delete an image from the TV"""
        try:
            # Look up content_id from our mapping
            content_id = self.file_mapping.get(filename)

            if content_id:
                logger.info(f"Deleting {filename} from TV {self.tv_ip} (content_id: {content_id})")
                await self.tv.delete(content_id)
                # Remove from mapping
                del self.file_mapping[filename]
                self._save_mapping()
                logger.info(f"Successfully deleted {filename} from TV {self.tv_ip}")
                return True
            else:
                logger.warning(f"Could not find {filename} in mapping for TV {self.tv_ip}")
                return False

        except Exception as e:
            logger.warning(f"Error deleting {filename} from TV {self.tv_ip}: {e}")
            return False

    async def sync(self, local_images: Set[str] = None) -> bool:
        """Synchronize artwork with the TV"""
        try:
            # Get local images if not provided
            if local_images is None:
                local_images = await self.get_local_images()

            # Get TV images
            tv_images = await self.get_tv_images()

            # Determine what to upload and delete
            to_upload = local_images - tv_images
            to_delete = tv_images - local_images

            logger.info(f"TV {self.tv_ip} sync: {len(to_upload)} to upload, {len(to_delete)} to delete")

            # If we're going to make changes, capture slideshow settings FIRST (before any operations)
            slideshow_settings = None
            if (to_upload or to_delete) and local_images:
                slideshow_settings = await self.get_slideshow_settings()

            # Upload new images
            for filename in to_upload:
                file_path = Path(ARTWORK_DIR) / filename
                await self.upload_image(file_path)
                # Small delay between uploads to avoid overwhelming the TV
                await asyncio.sleep(UPLOAD_DELAY)

            # Delete removed images
            for filename in to_delete:
                await self.delete_image(filename)
                await asyncio.sleep(DELETE_DELAY)

            # If we made changes and have images, select first image and restart slideshow
            if local_images and (to_upload or to_delete):

                first_image_content_id = list(self.file_mapping.values())[0] if self.file_mapping else None
                if first_image_content_id:
                    try:
                        logger.info(f"Selecting first image on TV {self.tv_ip} to prevent default art")
                        await self.tv.select_image(first_image_content_id, show=True)

                        # If slideshow was enabled, restart it with the same settings
                        if slideshow_settings:
                            await self.restart_slideshow(slideshow_settings)

                    except Exception as e:
                        logger.warning(f"Failed to select image on TV {self.tv_ip}: {e}")

            logger.info(f"Sync completed for TV {self.tv_ip}")
            return True

        except Exception as e:
            logger.warning(f"Error during sync for TV {self.tv_ip}: {e}")
            return False

    async def close(self):
        """Close connection to TV"""
        if self.tv:
            try:
                await self.tv.close()
            except:
                pass


async def sync_all_tvs():
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

    # Get local images once (shared by all TVs)
    logger.info(f"Syncing {len(connected_tvs)} connected TV(s)")
    local_images = await connected_tvs[0].get_local_images() if connected_tvs else set()

    # Sync all connected TVs with the same local images
    await asyncio.gather(*[tv.sync(local_images) for tv in connected_tvs])

    # Close all connections
    await asyncio.gather(*[tv.close() for tv in tv_syncs])

    logger.info("Sync cycle completed")


async def main():
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
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        sys.exit(0)
