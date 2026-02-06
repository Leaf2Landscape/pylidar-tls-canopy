#!/usr/bin/env python
"""
Extract SOP transformation matrices from a RISCAN project.rsp file
and save them as .DAT files.

Usage:
    python extract_transforms.py <project.rsp> [--output-dir DAT] [--use-sopv]
"""

import argparse
import re
import sys
from pathlib import Path


def extract_transforms(rsp_file, use_sopv=False):
    """
    Extract SOP or SOPV transformation matrices from project.rsp.

    Args:
        rsp_file: Path to project.rsp file
        use_sopv: If True, use SOPV matrices (voxel-aligned), else use SOP

    Returns:
        Dictionary mapping scan position names to 4x4 matrix strings
    """
    with open(rsp_file, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    transforms = {}

    # Pattern to find scanposition elements with their SOP/SOPV matrices
    # Match scanposition name and then find the appropriate matrix
    scanpos_pattern = r'<scanposition\s+name="(ScanPos\d+)"[^>]*>.*?</scanposition>'

    for match in re.finditer(scanpos_pattern, content, re.DOTALL):
        scanpos_name = match.group(1)
        scanpos_content = match.group(0)

        # Choose which matrix type to extract
        if use_sopv:
            # SOPV matrix (voxel-aligned)
            matrix_pattern = r'<sopv[^>]*>.*?<matrix[^>]*>\s*([\d\s.eE+-]+)\s*</matrix>'
        else:
            # SOP matrix (original)
            matrix_pattern = r'<sop name="SOP"[^>]*>.*?<matrix[^>]*>\s*([\d\s.eE+-]+)\s*</matrix>'

        matrix_match = re.search(matrix_pattern, scanpos_content, re.DOTALL)

        if matrix_match:
            matrix_values = matrix_match.group(1).strip()
            transforms[scanpos_name] = matrix_values

    return transforms


def format_matrix(matrix_str):
    """
    Format matrix values as a 4x4 matrix with proper spacing.

    Args:
        matrix_str: Space-separated matrix values (16 values)

    Returns:
        Formatted matrix string (4 rows)
    """
    values = matrix_str.split()

    if len(values) != 16:
        raise ValueError(f"Expected 16 matrix values, got {len(values)}")

    # Format each value with high precision
    formatted_values = []
    for v in values:
        try:
            num = float(v)
            formatted_values.append(f"{num:.16f}")
        except ValueError:
            formatted_values.append(v)

    # Arrange as 4x4 matrix
    rows = []
    for i in range(4):
        row_values = formatted_values[i*4:(i+1)*4]
        rows.append(' '.join(row_values))

    return '\n'.join(rows)


def main():
    parser = argparse.ArgumentParser(
        description='Extract SOP transforms from RISCAN project.rsp'
    )
    parser.add_argument(
        'rsp_file',
        help='Path to project.rsp file'
    )
    parser.add_argument(
        '-o', '--output-dir',
        default=None,
        help='Output directory for DAT files (default: DAT folder in project directory)'
    )
    parser.add_argument(
        '--use-sopv',
        action='store_true',
        help='Use SOPV (voxel-aligned) matrices instead of SOP'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without writing files'
    )

    args = parser.parse_args()

    rsp_path = Path(args.rsp_file)
    if not rsp_path.exists():
        print(f"Error: {rsp_path} not found")
        return 1

    # Determine output directory
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        # Default to DAT folder in project directory
        output_dir = rsp_path.parent / 'DAT'

    print(f"Reading: {rsp_path}")
    print(f"Output directory: {output_dir}")
    print(f"Matrix type: {'SOPV (voxel-aligned)' if args.use_sopv else 'SOP (original)'}")
    print()

    # Extract transforms
    transforms = extract_transforms(rsp_path, use_sopv=args.use_sopv)

    if not transforms:
        print("No transforms found in project.rsp")
        return 1

    print(f"Found {len(transforms)} scan positions with transforms")

    # Create output directory if needed
    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    # Write DAT files
    written = 0
    skipped = 0

    for scanpos_name, matrix_str in sorted(transforms.items()):
        dat_file = output_dir / f"{scanpos_name}.DAT"

        if dat_file.exists():
            print(f"  Skipping {scanpos_name} - DAT file already exists")
            skipped += 1
            continue

        try:
            formatted_matrix = format_matrix(matrix_str)

            if args.dry_run:
                print(f"  Would write {dat_file}")
            else:
                with open(dat_file, 'w') as f:
                    f.write(formatted_matrix + '\n')
                print(f"  Wrote {dat_file}")

            written += 1

        except ValueError as e:
            print(f"  Error processing {scanpos_name}: {e}")

    print()
    print(f"Summary: {written} written, {skipped} skipped (already exist)")

    return 0


if __name__ == '__main__':
    sys.exit(main())
