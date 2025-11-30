# Samsung Frame TV Artwork Sync

Automatically sync artwork from a local folder to multiple Samsung Frame TVs using Docker.

**Docker Hub:** [turley/frame-tv-artwork-sync](https://hub.docker.com/r/turley/frame-tv-artwork-sync)

## Features

- Sync artwork to multiple Frame TVs simultaneously
- Automatic periodic sync (configurable interval)
- Auto-cleanup: removes images from TVs when deleted locally
- Skips offline TVs and continues syncing others
- Configurable matte/border style
- Automatic slideshow restoration after sync
- Lightweight Alpine-based Docker image
- Persistent file tracking to avoid re-uploading

## Quick Start

### Using Docker Compose (Recommended)

1. Download [docker-compose.yml](docker-compose.yml)
2. Create folders and add your images:
   ```bash
   mkdir -p artwork tokens
   # Add your images to the artwork folder
   ```
3. Edit `docker-compose.yml` with your TV IP addresses
4. Run:

```bash
docker-compose up -d
```

On first run, approve the connection on each TV when prompted. Tokens are saved for future use.

### Using Docker CLI

```bash
# Create folders
mkdir -p artwork tokens

# Run container
docker run -d \
  --name frame-tv-sync \
  --restart unless-stopped \
  --network host \
  -e TV_IPS="192.168.1.100,192.168.1.101" \
  -e SYNC_INTERVAL_MINUTES="5" \
  -e MATTE_STYLE="none" \
  -v ./artwork:/artwork \
  -v ./tokens:/tokens \
  turley/frame-tv-artwork-sync
```

## Configuration

All settings are configured via environment variables in [docker-compose.yml](docker-compose.yml):

| Variable                   | Description                                                                               | Default   |
| -------------------------- | ----------------------------------------------------------------------------------------- | --------- |
| `TV_IPS`                   | Comma-separated TV IP addresses (required)                                                | -         |
| `SYNC_INTERVAL_MINUTES`    | How often to sync (in minutes)                                                            | `5`       |
| `MATTE_STYLE`              | Border style (see [Matte Styles](#matte-styles) below)                                    | `none`    |
| `SLIDESHOW_ENABLED`        | Enable slideshow (true/false) - overrides TV settings if set                              | (unset)   |
| `SLIDESHOW_INTERVAL`       | Slideshow interval in minutes (use values supported by your TV model)                     | `15`      |
| `SLIDESHOW_TYPE`           | Slideshow type: `shuffle` or `sequential` - requires override enabled                     | `shuffle` |
| `BRIGHTNESS`               | Manual brightness override (use values supported by your TV model, commonly 0-10 or 0-50) | (unset)   |
| `SOLAR_BRIGHTNESS_ENABLED` | Enable automatic solar-based brightness adjustment (true/false)                           | (unset)   |
| `LOCATION_LATITUDE`        | Latitude for solar calculations (e.g., 42.3601)                                           | -         |
| `LOCATION_LONGITUDE`       | Longitude for solar calculations (e.g., -71.0589)                                         | -         |
| `LOCATION_TIMEZONE`        | Timezone name (e.g., America/New_York)                                                    | `UTC`     |
| `BRIGHTNESS_MIN`           | Minimum brightness when sun is below horizon                                              | `2`       |
| `BRIGHTNESS_MAX`           | Maximum brightness when sun is at zenith (90°)                                            | `10`      |

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
- Set `BRIGHTNESS_MIN` (brightness when sun is below horizon) and `BRIGHTNESS_MAX` (brightness at maximum solar irradiance)
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

**Note:** Brightness ranges vary by TV model year. Common ranges are 0-10 or 0-50. Check your TV's settings menu to see which values are supported by your specific model.

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

## How It Works

### Slideshow Restoration

When the sync script uploads new images or deletes old ones, it automatically:

1. **Captures** your current slideshow settings before making changes
2. **Syncs** the artwork (uploads new, deletes removed)
3. **Selects** the first image to prevent the TV from showing default art
4. **Restores** your slideshow settings so rotation continues automatically

This ensures your slideshow keeps running seamlessly after each sync.

### Debug Logging

Set `LOG_LEVEL=DEBUG` in your environment to see detailed sync operations:

```bash
docker-compose logs -f
```

## Requirements

- Samsung Frame TV (2016+ models with Tizen OS)
- Docker and Docker Compose
- Network access to TVs

## Credits

Built using [samsung-tv-ws-api](https://github.com/NickWaterton/samsung-tv-ws-api) by NickWaterton.

## AI Disclosure

This project was created with the assistance of AI tools.

## License

MIT
