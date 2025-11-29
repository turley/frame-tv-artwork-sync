# Samsung Frame TV Artwork Sync

Automatically sync artwork from a local folder to multiple Samsung Frame TVs using Docker.

**Docker Hub:** [turley/frame-tv-artwork-sync](https://hub.docker.com/r/turley/frame-tv-artwork-sync)

## Features

- Sync artwork to multiple Frame TVs simultaneously
- Automatic periodic sync (configurable interval)
- Auto-cleanup: removes images from TVs when deleted locally
- Skips offline TVs and continues syncing others
- Configurable matte/border style
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

| Variable                | Description                                            | Default |
| ----------------------- | ------------------------------------------------------ | ------- |
| `TV_IPS`                | Comma-separated TV IP addresses (required)             | -       |
| `SYNC_INTERVAL_MINUTES` | How often to sync (in minutes)                         | `5`     |
| `MATTE_STYLE`           | Border style (see [Matte Styles](#matte-styles) below) | `none`  |

**Note:** Slideshow interval and brightness must be configured manually via the SmartThings app or TV settings.

## Supported Image Formats

JPG, JPEG, PNG, BMP, TIF, TIFF

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
pip install git+https://github.com/NickWaterton/samsung-tv-ws-api.git
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

## Logs

View logs to monitor sync status:

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
