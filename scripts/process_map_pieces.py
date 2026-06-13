#!/usr/bin/env python3
"""
Batch process the generated map pieces using rembg to remove their white backgrounds.
By default, processes files in static/map-pieces/ in-place.

Usage:
    python3 scripts/process_map_pieces.py
    python3 scripts/process_map_pieces.py --src ~/Downloads
"""

import os
import sys
import argparse
from pathlib import Path

# Activate your virtualenv before running, or install rembg + pillow globally

try:
    from rembg import remove
    from PIL import Image
except ImportError:
    print("Error: Required libraries not found. Please install them:")
    print("  pip install \"rembg[cpu]\" pillow")
    sys.exit(1)

ROOT = Path(__file__).parent.parent
DEFAULT_DEST = ROOT / "static" / "map-pieces"

# Expected map piece names
ZONE_IDS = [
    "SOUL_JAZZ", "FOLK_SINGER", "ELECTRONIC_HIP", "INDIE_WORLD",
    "DRAMA", "CRIME_THRILLER", "ARTHOUSE", "SCI_FI",
    "FANTASY_COMEDY", "ACTION_ADV", "ANIMATION", "HISTORY"
]

def process_file(src_path: Path, dest_path: Path):
    print(f"Processing: {src_path.name} -> {dest_path.name}")
    try:
        with open(src_path, 'rb') as i:
            input_data = i.read()
            output_data = remove(input_data)
        
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, 'wb') as o:
            o.write(output_data)
        print(f"  Saved to {dest_path}")
        return True
    except Exception as e:
        print(f"  Error processing {src_path.name}: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Batch process map piece images using rembg.")
    parser.add_argument("--src", type=str, help="Source directory containing raw images. If omitted, uses destination directory (in-place processing).")
    parser.add_argument("--dest", type=str, default=str(DEFAULT_DEST), help="Destination directory for processed images.")
    args = parser.parse_args()

    dest_dir = Path(args.dest)
    
    if args.src:
        src_dir = Path(os.path.expanduser(args.src))
        if not src_dir.exists():
            print(f"Error: Source directory '{src_dir}' does not exist.")
            sys.exit(1)
        
        # Look for files matching the expected zone IDs in the source directory
        files = os.listdir(src_dir)
        processed_count = 0
        
        for zone in ZONE_IDS:
            # Find any file starting with zone name (case-insensitive) and ending with .png
            match = [f for f in files if f.upper().startswith(zone) and f.lower().endswith(".png")]
            if match:
                # Use the latest matching file if multiple
                match.sort()
                src_file = src_dir / match[-1]
                dest_file = dest_dir / f"{zone}.png"
                if process_file(src_file, dest_file):
                    processed_count += 1
            else:
                print(f"Note: No source file found for zone {zone} in '{src_dir}'")
                
        print(f"\nDone. Processed {processed_count} files from source directory.")
    else:
        # In-place processing of existing files in the destination directory
        if not dest_dir.exists():
            print(f"Error: Destination directory '{dest_dir}' does not exist.")
            sys.exit(1)
            
        files = [f for f in os.listdir(dest_dir) if f.upper().endswith(".png") and f.replace(".png", "").upper() in ZONE_IDS]
        if not files:
            print(f"No map pieces found in '{dest_dir}' to process in-place.")
            sys.exit(0)
            
        print(f"Found {len(files)} map piece(s) in '{dest_dir}'. Starting in-place processing...")
        processed_count = 0
        for filename in files:
            file_path = dest_dir / filename
            
            # Read first to check if it already has transparency (optional, but clean)
            try:
                with Image.open(file_path) as img:
                    if img.mode == 'RGBA':
                        # Check if it has any transparent pixels
                        extrema = img.getextrema()
                        if len(extrema) == 4 and extrema[3][0] < 255:
                            print(f"Skipping {filename} (already has transparency)")
                            continue
            except Exception:
                pass # Fall back to processing
                
            if process_file(file_path, file_path):
                processed_count += 1
                
        print(f"\nDone. Processed {processed_count} files in-place.")

if __name__ == "__main__":
    main()
