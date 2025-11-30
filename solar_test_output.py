"""
Solar brightness test output module.

Provides formatted output for testing solar brightness calculations.
Used by sync_artwork.py when invoked with --test-solar flag to preview
brightness levels throughout the year without connecting to TVs.

Functions:
    - print_hourly_brightness: Display brightness for each hour of a specific date
    - run_solar_brightness_test: Run complete test for solstices and equinoxes
    - print_test_error: Show helpful error message when location not configured
"""

import datetime
import zoneinfo
from typing import Callable
from pysolar.solar import get_altitude


def print_hourly_brightness(
    year: int,
    month: int,
    day: int,
    date_name: str,
    latitude: float,
    longitude: float,
    timezone: str,
    brightness_min: int,
    brightness_max: int,
    calculate_brightness_func: Callable[[float], int]
):
    """Print hourly brightness levels for a specific date"""

    tz = zoneinfo.ZoneInfo(timezone)

    print(f"\n{'='*80}")
    print(f"{date_name} - {year}/{month:02d}/{day:02d}")
    print(f"Location: {latitude}°, {longitude}° ({timezone})")
    print(f"Brightness range: {brightness_min} (min) to {brightness_max} (max)")
    print(f"{'='*80}")
    print(f"{'Time':<12} {'Sun Elevation':<20} {'Brightness':<15} {'Visual'}")
    print(f"{'-'*80}")

    for hour in range(24):
        local_time = datetime.datetime(year, month, day, hour, 0, 0, tzinfo=tz)
        utc_time = local_time.astimezone(datetime.timezone.utc)

        elevation = get_altitude(latitude, longitude, utc_time)
        brightness = calculate_brightness_func(elevation)

        # Create visual bar
        bar_length = int((brightness - brightness_min) / (brightness_max - brightness_min) * 40) if brightness_max > brightness_min else 0
        bar = '█' * bar_length

        # Format elevation display
        if elevation < 0:
            elev_str = f"{elevation:6.2f}° (below)"
        else:
            elev_str = f"{elevation:6.2f}°"

        print(f"{local_time.strftime('%I:%M %p'):<12} {elev_str:<20} {brightness:<15} {bar}")


def run_solar_brightness_test(
    latitude: float,
    longitude: float,
    timezone: str,
    brightness_min: int,
    brightness_max: int,
    calculate_brightness_func: Callable[[float], int]
):
    """Run complete solar brightness test for solstices and equinox"""

    current_year = datetime.datetime.now().year

    # Test dates: key solar positions throughout the year
    # Using hemisphere-neutral naming (seasons are reversed in southern hemisphere)
    test_dates = [
        (current_year, 3, 20, "March Equinox"),
        (current_year, 6, 21, "June Solstice"),
        (current_year, 12, 21, "December Solstice")
    ]

    for year, month, day, date_name in test_dates:
        print_hourly_brightness(
            year, month, day, date_name,
            latitude, longitude, timezone,
            brightness_min, brightness_max,
            calculate_brightness_func
        )

    print("\n" + "="*80)
    print("Calculation Method:")
    print("  - Sun below horizon (≤0°): brightness = BRIGHTNESS_MIN")
    print("  - Above horizon: Physics-based atmospheric air mass model")
    print("    • Air Mass = 1 / (sin(elev) + 0.50572×(elev+6.07995)^-1.6364) [Kasten-Young]")
    print("    • Relative Irradiance = 0.7^(AM^0.678)")
    print("    • Brightness = MIN + (MAX - MIN) × Relative Irradiance")
    print("  - This models how sunlight intensity changes through atmosphere")
    print("="*80 + "\n")


def print_test_error(message: str):
    """Print error message for test mode"""
    print("\n" + "="*80)
    print(f"ERROR: {message}")
    print("="*80)
    print("\nPlease set the following environment variables:")
    print("  LOCATION_LATITUDE    (e.g., 42.3601)")
    print("  LOCATION_LONGITUDE   (e.g., -71.0589)")
    print("  LOCATION_TIMEZONE    (e.g., America/New_York)")
    print("\nOptional:")
    print("  BRIGHTNESS_MIN       (default: 2)")
    print("  BRIGHTNESS_MAX       (default: 10)")
    print("\nExample:")
    print("  export LOCATION_LATITUDE=42.3601")
    print("  export LOCATION_LONGITUDE=-71.0589")
    print("  export LOCATION_TIMEZONE=America/New_York")
    print("  python sync_artwork.py --test-solar")
    print("\n" + "="*80)
