# Samsung Frame TV Artwork Sync

Automatically sync artwork from a local folder to Samsung Frame TVs using Docker.

**Docker Hub:** [turley/frame-tv-artwork-sync](https://hub.docker.com/r/turley/frame-tv-artwork-sync)

## New! 2024 Model Support

This project has been updated to fully support **2024 Samsung Frame TVs (LS03D)** and newer firmware (v2.0.25+) while maintaining **100% backward compatibility** with older models. Key features include:

- **Silent REST Gate**: Probes the TV's Art Service (`/ms/art`) before connecting. If you are watching an app (Netflix, YouTube, etc.), the script exits silently, preventing disruptive popups.
- **Port 8002 for Token Persistence**: 2024 models require Port 8002 for the WebSocket token exchange. This ensures auth tokens are saved correctly to your `/tokens` volume.
- **Unique App Identity (`TV_NAME`)**: Standardized as `Frame_Photo_Sync` to create a permanent trust profile, eliminating "Samsung Remote" prompts.
- **Wake-on-LAN**: Automatically wake sleeping TVs before syncing using their MAC address.
- **System Insight**: Automatically logs your TV's Model and Firmware version for easier troubleshooting.
- **Connection Diagnostics**: Includes `test_connection.py` for troubleshooting connectivity and token persistence.

## Features

- Sync artwork to one or multiple Frame TVs
- Automatic periodic sync (configurable interval)
- Auto-cleanup: removes images from TVs when deleted locally
- Persistent file tracking to avoid re-uploading
- Configurable matte/border style
- Slideshow control: preserve TV settings or override with custom interval/type
- Optional solar-based brightness adjustment using sun position and atmospheric modeling
- Manual brightness control with fixed values
- Skips offline TVs and continues syncing others
- Skips TVs not in art mode (e.g., when watching content via HDMI)
- Lightweight Alpine-based Docker image

## Quick Start

### Using Docker Compose (Recommended)

1. Download [docker-compose.yml](docker-compose.yml)
2. Create folders:
   ```bash
   mkdir -p artwork tokens
   ```
3. Add your images to the artwork folder
4. Edit `docker-compose.yml` with your TV IP addresses
5. Run:
   ```bash
   docker-compose up -d
   ```

On first run, approve the connection on each TV when prompted. Tokens are saved for future use.

> **📺 Viewing your uploaded photos on the TV:**
> After the first sync, your photos won't appear automatically — the TV defaults to Samsung's built-in art gallery. To switch to your uploaded images:
> **Art Mode → Art Store → My Photos**
> Your synced collection will be there. Enable slideshow from the same menu to have them rotate automatically.

### Using Docker CLI

```bash
# Create folders
mkdir -p artwork tokens

# Run container
docker run -d \
  --name frame-tv-sync \
  --restart unless-stopped \
  -e TV_IPS="192.168.1.100,192.168.1.101" \
  -e TV_PORT="8002" \
  -e TV_NAME="Frame_Photo_Sync" \
  -e SYNC_INTERVAL_MINUTES="15" \
  -v ./artwork:/artwork \
  -v ./tokens:/tokens \
  turley/frame-tv-artwork-sync
```

## Configuration

All settings are configured via environment variables:

| Variable                   | Description                                                                               | Default      |
| -------------------------- | ----------------------------------------------------------------------------------------- | ------------ |
| `TV_IPS`                   | Comma-separated TV IP addresses (required)                                                | -            |
| `TV_PORT`                  | Connection port. Defaults to **`8002`** for 2024+ model persistence.       | `8002`       |
| `TV_NAME`                  | App identity for the handshake. Defaults to **`Frame_Photo_Sync`**.              | `Frame_Photo_Sync` |
| `TV_MAC`                   | TV MAC Address for Wake-on-LAN (wakes sleeping TVs before sync)                           | (unset)      |
| `SYNC_INTERVAL_MINUTES`    | How often to sync (in minutes). Defaults to **`15`** for stability.                                                            | `15`          |
| `MATTE_STYLE`              | Border style (see [Matte Styles](#matte-styles) below)                                    | `none`       |
| `SLIDESHOW_ENABLED`        | Enable slideshow (true/false) - overrides TV settings if set                              | (unset)      |
| `SLIDESHOW_INTERVAL`       | Slideshow interval in minutes (use values supported by your TV model)                     | `15`         |
| `SLIDESHOW_TYPE`           | Slideshow type: `shuffle` or `sequential`                                                 | `shuffle`    |
| `BRIGHTNESS`               | Manual brightness override (use values supported by your TV model, commonly 0-10 or 0-50) | (unset)      |
| `SOLAR_BRIGHTNESS_ENABLED` | Enable automatic solar-based brightness adjustment (true/false)                           | (unset)      |
| `LOCATION_LATITUDE`        | Latitude for solar calculations (e.g., 42.3601)                                           | -            |
| `LOCATION_LONGITUDE`       | Longitude for solar calculations (e.g., -71.0589)                                         | -            |
| `LOCATION_TIMEZONE`        | Timezone name (e.g., America/New_York)                                                    | `UTC`        |
| `BRIGHTNESS_MIN`           | Minimum brightness when sun is below horizon                                              | `2`          |
| `BRIGHTNESS_MAX`           | Maximum brightness if sun were at zenith (90°)                                            | `10`         |
| `REMOVE_UNKNOWN_IMAGES`    | Remove images from TV that aren't in the artwork folder (true/false)                      | `false`      |
| `AUTO_OFF_TIME`            | Time to turn off TVs in art mode (24-hour format, e.g., `22:00`)                          | (unset)      |
| `AUTO_OFF_GRACE_HOURS`     | Hours after `AUTO_OFF_TIME` to keep trying to turn off TVs                                | `2`          |

### Slideshow & Brightness Control

#### Slideshow Settings

**Default Behavior (no override variables set):**

- When images are added or removed during sync, the script preserves and restores your TV's current slideshow settings
- If no images change, slideshow settings are not modified

**Override Behavior (if any slideshow variable is set):**

- When images are added or removed during sync, the script applies slideshow settings from environment variables
- If you set `SLIDESHOW_ENABLED`, `SLIDESHOW_INTERVAL`, or `SLIDESHOW_TYPE`, all slideshow variables use defaults for any unset values
- If no images change, slideshow settings are not modified

**Note:** Slideshow interval values vary by TV model year. Common values include 3, 15, 60, 720, 1440 minutes. Check your TV's slideshow settings menu to see which intervals are supported by your specific model.

#### Brightness Control

**Manual Brightness:**

- Set `BRIGHTNESS` to a fixed value (commonly 0-10 or 0-50 depending on your TV model)
- Applied every sync run when set

**Solar-Based Brightness (Automatic):**

- Enable `SOLAR_BRIGHTNESS_ENABLED=true` to automatically adjust brightness based on sun position
- Requires `LOCATION_LATITUDE`, `LOCATION_LONGITUDE`, and `LOCATION_TIMEZONE`
- Set `BRIGHTNESS_MIN` (brightness when sun is below horizon) and `BRIGHTNESS_MAX` (brightness for sun at zenith)
- Brightness is calculated every sync run using physics-based atmospheric air mass model
- Uses Kasten-Young formula to model how sunlight intensity changes through the atmosphere
- Takes precedence over manual `BRIGHTNESS` setting when enabled

**Example Solar Setup:**

```bash
SOLAR_BRIGHTNESS_ENABLED=true
LOCATION_LATITUDE=42.3601
LOCATION_LONGITUDE=-71.0589
LOCATION_TIMEZONE=America/New_York
BRIGHTNESS_MIN=2
BRIGHTNESS_MAX=10
```

With this configuration (example for Boston, MA):

- At night (sun below horizon): brightness = 2
- At solar noon in summer (sun ~71°): brightness ≈ 7
- At solar noon in winter (sun ~24°): brightness ≈ 6
- At sunrise/sunset (sun near 0°): brightness = 2

**Testing Solar Brightness:**

To preview how brightness will change throughout the year at your location:

```bash
# Set your location variables
export LOCATION_LATITUDE=42.3601
export LOCATION_LONGITUDE=-71.0589
export LOCATION_TIMEZONE=America/New_York
export BRIGHTNESS_MIN=2
export BRIGHTNESS_MAX=10

# Run in test mode
python sync_artwork.py --test-solar
```

This displays hourly brightness levels for key solar positions (March Equinox, June Solstice, December Solstice), helping you verify your settings before deploying.

### Image Cleanup Control

**`REMOVE_UNKNOWN_IMAGES`** - Controls whether the script removes images from your TV that aren't in your local artwork folder.

**Default behavior (`REMOVE_UNKNOWN_IMAGES=false` or unset):**

- Preserves any images already on the TV that were uploaded manually or before the script started tracking
- Only manages images that the script has uploaded
- Logs a warning when unknown images are detected, listing their content IDs

**When enabled (`REMOVE_UNKNOWN_IMAGES=true`):**

- Removes any images from the TV that aren't in your local artwork folder
- Ensures your TV only displays images from your synced collection
- Useful for maintaining a "clean slate" that exactly matches your local folder

### Auto-Off Control

**`AUTO_OFF_TIME`** - Automatically turn off TVs at a specific time, but only when they're in art mode. This feature only works on some Frame TV models.

This feature is useful when you want TVs to turn off at night but only if they're displaying art. If someone is actively watching the TV, it won't be interrupted.

**How it works:**

- Set `AUTO_OFF_TIME` to a time in 24-hour format (e.g., `22:00` for 10 PM)
- The script checks during each sync if the current time is within the turn-off window
- If a TV is in art mode during this window, it will be turned off after the sync completes
- TVs not in art mode (e.g., watching HDMI content) are left alone

**Grace period:**

- `AUTO_OFF_GRACE_HOURS` defines how long after `AUTO_OFF_TIME` the script will keep trying to turn off TVs
- Default is 2 hours, so if `AUTO_OFF_TIME=22:00`, it will try until midnight
- After the grace period ends, the script stops attempting to turn off TVs until the next day
- This handles cases where a TV wasn't in art mode at the exact off time

**Example setup:**

```bash
AUTO_OFF_TIME=22:00
AUTO_OFF_GRACE_HOURS=2
LOCATION_TIMEZONE=America/New_York
```

With this configuration:

- Starting at 10 PM (in your timezone), TVs in art mode will be turned off after sync
- If a TV is being used at 10 PM but returns to art mode by 11 PM, it will be turned off then
- After midnight, no turn-off attempts are made until the next day's 10 PM

**Note:** `LOCATION_TIMEZONE` is required for this feature to work correctly.

## Image Requirements

**Supported Formats:** JPEG, JPG, PNG

**Recommended Specs:**

- Resolution: 3840 x 2160 pixels (4K) for 43"+ TVs, 1920 x 1080 for 32" TVs
- Aspect ratio: 16:9
- File size: Under 20MB
- Color space: sRGB

## Matte Styles

Matte styles combine a border **style** with a **color** in the format `{style}_{color}`, or use `none` for no border.

**Available Styles:**
`modernthin`, `modern`, `modernwide`, `flexible`, `shadowbox`, `panoramic`, `triptych`, `mix`, `squares`

**Available Colors:**
`black`, `neutral`, `antique`, `warm`, `polar`, `sand`, `seafoam`, `sage`, `burgandy`, `navy`, `apricot`, `byzantine`, `lavender`, `redorange`, `skyblue`, `turquoise`

**Examples:**

- `shadowbox_polar` - shadowbox border in polar color
- `modern_apricot` - modern border in apricot color
- `flexible_antique` - flexible border in antique color
- `none` - no border (full screen)

## Local Testing

To test without Docker:

1. **Install dependencies:**

```bash
pip install git+https://github.com/NickWaterton/samsung-tv-ws-api.git pysolar
```

2. **Set up environment:**

```bash
# Copy and edit with your TV IP
cp .env.example .env

# Create directories
mkdir -p artwork tokens

# Add test images to artwork folder
```

3. **Run the script:**

```bash
export $(grep -v '^#' .env | xargs) && python sync_artwork.py
```

On first run, approve the connection on your TV. Press `Ctrl+C` to stop.

**Testing solar brightness calculations:**

If you've configured solar brightness settings, test them before running the full sync:

```bash
export $(grep -v '^#' .env | xargs) && python sync_artwork.py --test-solar
```

This shows hourly brightness predictions for key solar positions (March Equinox, June Solstice, December Solstice) without connecting to TVs.

**Dry run mode:**

Preview what changes would be made without actually modifying your TVs:

```bash
export $(grep -v '^#' .env | xargs) && python sync_artwork.py --dry-run
```

This connects to TVs to read their current state but won't upload, delete, or modify any settings.

## How It Works

### Slideshow Behavior

When the sync script uploads new images or deletes old ones:

1. **Syncs** the artwork (uploads new, deletes removed)
2. **Selects** an image to prevent the TV from showing default art (random image for shuffle mode, first image otherwise)
3. **Applies slideshow settings** based on your configuration:
   - If slideshow override variables are set (`SLIDESHOW_ENABLED`, `SLIDESHOW_INTERVAL`, or `SLIDESHOW_TYPE`), uses those settings
   - If no override variables are set, preserves and restores your TV's current slideshow settings

If no images change during a sync cycle, slideshow settings are not modified.

## Requirements

- Samsung Frame TV (2016+ models with Tizen OS)
- Docker and Docker Compose (or Python 3.9+ for local testing)
- Network access to TVs

### Debug Logging

Set `LOG_LEVEL=DEBUG` in your environment to see detailed sync operations and TV responses.

### 2024 Models & Firmware Updates (v2.0.25+)

Recent Samsung Frame TV firmware (notably on 2024 LS03D models) has increased security requirements. Here's what you need to know:

1.  **Use Port 8002** (Critical):
    Set `TV_PORT=8002`. Port 8001 will connect to the TV but **does not perform the WebSocket token exchange**, meaning the TV will prompt "Allow/Deny" on every container restart. Port 8002 is required for the token to be saved to your `/tokens` volume.
2.  **Set a Unique `TV_NAME`** (Critical):
    Set `TV_NAME` to a unique identifier (e.g., `ArtSync_MyServer`). The default `Samsung TV` creates a generic trust profile that can be overwritten by other apps. A unique name gives your container its own permanent trust slot on the TV.
3.  **Use `TV_MAC` (Wake-on-LAN)**:
    Set your TV's MAC address in `TV_MAC` (e.g., `20:15:DE:31:D9:40`). This allows the script to send a "Magic Packet" to wake up the TV's network port if it's in a deep sleep.
4.  **Clear the Device List** (if stuck):
    If no popup appears, go to **Settings > Connection > External Device Manager > Device Connection Manager > Device List** on your TV and delete any existing entry for "Samsung TV" or "python" before restarting the container.

**Diagnostics:**

A `test_connection.py` script is included for troubleshooting. Run it inside the container:

```bash
docker exec frame-tv-sync python3 /app/test_connection.py
```

This tests TCP connectivity, library API compatibility, token persistence, and performs a live WebSocket handshake.

**Viewing your photos after sync:**

After a successful upload, your photos won't appear automatically on the TV — it defaults to Samsung's own gallery. Navigate to:
> **Art Mode → Art Store → My Photos**

Your uploaded images will be there. Enable the slideshow from this menu to cycle through your collection automatically.

## Credits

Built using [samsung-tv-ws-api](https://github.com/NickWaterton/samsung-tv-ws-api) by NickWaterton.

## AI Disclosure

This project was created with the assistance of AI tools.

## License

MIT
