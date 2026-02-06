#!/usr/bin/env python
"""
Batch generate hemispherical (fisheye) images from TLS scans in a RISCAN project.

This script processes all ScanPos directories in a RISCAN project and generates
hemispherical projection images from the spherical coordinate data.

Two input modes are supported:
1. From RISCAN project: Process raw scan data directly
2. From GeoTIFF grids: Convert existing spherical grid files (--from-grids)

Supports two projection types:
- Equidistant (linear zenith mapping): preserves angular distances
- Equisolid-angle: preserves relative areas (better for canopy gap fraction analysis)
"""

import os
import sys
import argparse
from pathlib import Path
import glob as globlib
import numpy as np
from PIL import Image
import rasterio
from tqdm import tqdm

from pylidar_tls_canopy import riegl_io, grid


def find_scan_positions(riscan_project):
    """
    Find all scan positions in a RISCAN project.

    Args:
        riscan_project: Path to RISCAN project directory (.RiSCAN folder)

    Returns:
        List of scan position directories
    """
    project_path = Path(riscan_project)
    scans_dir = project_path / "SCANS"

    if not scans_dir.exists():
        raise FileNotFoundError(f"SCANS directory not found in {riscan_project}")

    # Find all ScanPos directories
    scan_positions = sorted([d for d in scans_dir.iterdir()
                            if d.is_dir() and d.name.startswith("ScanPos")])

    return scan_positions


def get_scan_files(scan_pos_dir, project_path, dat_dir=None):
    """
    Get RXP, RDBX, and transform file paths for a scan position.

    Args:
        scan_pos_dir: Path to ScanPos directory
        project_path: Path to RISCAN project root
        dat_dir: Optional custom directory for .DAT transform files

    Returns:
        Dictionary with rxp_file, rdbx_file, and transform_file paths
    """
    scan_pos_name = scan_pos_dir.name

    # Find RXP file in SCANS/ScanPosXXX/SINGLESCANS/
    singlescans_dir = scan_pos_dir / "SINGLESCANS"
    if not singlescans_dir.exists():
        return None

    rxp_file = None
    scan_name = None

    # First, check for subdirectories (standard RISCAN structure)
    singlescan_dirs = [d for d in singlescans_dir.iterdir() if d.is_dir()]
    if singlescan_dirs:
        singlescan_dir = singlescan_dirs[0]
        scan_name = singlescan_dir.name
        potential_rxp = singlescan_dir / f"{scan_name}.rxp"
        if potential_rxp.exists():
            rxp_file = potential_rxp

    # If not found in subdirectory, check for RXP files directly in SINGLESCANS
    if rxp_file is None:
        rxp_files = [f for f in singlescans_dir.glob("*.rxp")
                     if not f.name.endswith('.residual.rxp')]
        if rxp_files:
            rxp_file = rxp_files[0]
            scan_name = rxp_file.stem

    if rxp_file is None:
        return None

    # RDBX file in project.rdb/SCANS/ScanPosXXX/SINGLESCANS/scan_name/
    rdbx_file = project_path / "project.rdb" / "SCANS" / scan_pos_name / "SINGLESCANS" / scan_name / f"{scan_name}.rdbx"

    # Transform file - check custom directory first if provided, then standard locations
    transform_file = None

    if dat_dir is not None:
        # Check custom DAT directory
        custom_dat = Path(dat_dir) / f"{scan_pos_name}.DAT"
        if custom_dat.exists():
            transform_file = custom_dat

    # Fall back to standard locations if not found in custom directory
    if transform_file is None or not transform_file.exists():
        transform_file = project_path / "DAT" / f"{scan_pos_name}.DAT"
        if not transform_file.exists():
            transform_file = project_path / "project.rdb" / "SCANS" / f"{scan_pos_name}.DAT"

    if not transform_file.exists():
        return None

    return {
        'rxp_file': str(rxp_file),
        'rdbx_file': str(rdbx_file) if rdbx_file.exists() else None,
        'transform_file': str(transform_file),
        'scan_name': scan_name,
        'scan_pos': scan_pos_name
    }


def create_spherical_grid(scan_info, resolution, attribute='reflectance',
                          method='MEAN', query_str=None):
    """
    Create a spherical coordinate grid from scan data.

    Args:
        scan_info: Dictionary with scan file paths
        resolution: Angular resolution in degrees
        attribute: Attribute to grid (reflectance, range, intensity)
        method: Aggregation method (MEAN, MAX, MIN, SUM)
        query_str: Optional query string for filtering points

    Returns:
        2D numpy array with spherical grid data, or None on failure
    """
    # Use RDBX if available, otherwise RXP
    if scan_info['rdbx_file'] is not None and os.path.exists(scan_info['rdbx_file']):
        driver = 'rdbx'
        scan_file = scan_info['rdbx_file']
    else:
        driver = 'rxp'
        scan_file = scan_info['rxp_file']

    spherical_grid = grid.grid_riegl_spherical(
        scan_file,
        scan_info['transform_file'],
        resolution,
        attribute=attribute,
        method=method,
        query_str=query_str,
        driver=driver
    )

    return spherical_grid


def spherical_to_hemispherical(spherical_grid, size=1024, view='upper',
                                projection='equidistant', nodata=-9999):
    """
    Convert a spherical grid to a hemispherical (fisheye) projection image.

    Args:
        spherical_grid: 2D or 3D numpy array with shape (bands, zenith, azimuth)
                        Zenith: rows from 0 (up) to pi (down)
                        Azimuth: columns from 0 to 2*pi
        size: Output image size in pixels (square)
        view: 'upper' (looking up, zenith 0-90) or 'lower' (looking down, zenith 90-180)
        projection: 'equidistant' (r = theta) or 'equisolid' (r = 2*sin(theta/2))
        nodata: NoData value in input grid

    Returns:
        2D numpy array with hemispherical image
    """
    # Handle 3D input (take first band)
    if spherical_grid.ndim == 3:
        data = spherical_grid[0]
    else:
        data = spherical_grid

    nrows, ncols = data.shape
    zenith_res = np.pi / (nrows - 1)
    azimuth_res = 2 * np.pi / (ncols - 1)

    # Create output image
    img = np.full((size, size), np.nan, dtype=np.float32)
    center = size / 2.0

    # Create coordinate grids for vectorized computation
    y_coords, x_coords = np.mgrid[0:size, 0:size]

    # Convert to normalized coordinates (-1 to 1)
    nx = (x_coords - center) / center
    ny = (y_coords - center) / center
    r = np.sqrt(nx**2 + ny**2)

    # Mask pixels outside the hemisphere
    valid_mask = r <= 1.0

    # Calculate azimuth for all pixels (0 at top, clockwise)
    # North is up in the image
    azimuth = np.arctan2(nx, -ny) % (2 * np.pi)

    # Calculate zenith based on projection type
    if projection == 'equidistant':
        # Linear mapping: r proportional to zenith angle
        if view == 'upper':
            zenith = r * (np.pi / 2)  # 0 to pi/2
        else:
            zenith = (np.pi / 2) + r * (np.pi / 2)  # pi/2 to pi
    elif projection == 'equisolid':
        # Equisolid-angle: r = 2 * sin(theta/2) -> theta = 2 * arcsin(r/2)
        # This preserves relative areas
        if view == 'upper':
            zenith = 2 * np.arcsin(r / 2) * (np.pi / 2) / (2 * np.arcsin(0.5))
        else:
            half_zenith = 2 * np.arcsin(r / 2) * (np.pi / 2) / (2 * np.arcsin(0.5))
            zenith = (np.pi / 2) + half_zenith
    else:
        raise ValueError(f"Unknown projection type: {projection}")

    # Map to grid indices
    row_idx = (zenith / zenith_res).astype(int)
    col_idx = (azimuth / azimuth_res).astype(int)

    # Clamp indices to valid range
    row_idx = np.clip(row_idx, 0, nrows - 1)
    col_idx = np.clip(col_idx, 0, ncols - 1)

    # Sample from spherical grid
    sampled = data[row_idx, col_idx]

    # Apply valid mask and nodata mask
    sampled[~valid_mask] = np.nan
    sampled[sampled == nodata] = np.nan

    return sampled


def normalize_and_colorize(img, colormap='gray', vmin=None, vmax=None,
                           percentile_clip=2):
    """
    Normalize image data and convert to RGB.

    Args:
        img: 2D numpy array with image data
        colormap: Colormap name ('gray', 'viridis', 'plasma', 'inferno')
        vmin: Minimum value for normalization (None = auto)
        vmax: Maximum value for normalization (None = auto)
        percentile_clip: Percentile for auto min/max clipping

    Returns:
        PIL Image object (RGB)
    """
    import matplotlib.pyplot as plt
    from matplotlib import cm

    # Get valid (non-NaN) values
    valid = img[~np.isnan(img)]

    if len(valid) == 0:
        # All NaN - return black image
        return Image.fromarray(np.zeros((*img.shape, 3), dtype=np.uint8))

    # Auto-calculate min/max if not provided
    if vmin is None:
        vmin = np.percentile(valid, percentile_clip)
    if vmax is None:
        vmax = np.percentile(valid, 100 - percentile_clip)

    # Normalize to 0-1
    normalized = (img - vmin) / (vmax - vmin + 1e-10)
    normalized = np.clip(normalized, 0, 1)

    # Apply colormap
    cmap = cm.get_cmap(colormap)
    colored = cmap(normalized)

    # Set NaN pixels to black (or transparent)
    colored[np.isnan(img)] = [0, 0, 0, 1]

    # Convert to 8-bit RGB
    rgb = (colored[:, :, :3] * 255).astype(np.uint8)

    return Image.fromarray(rgb)


def load_spherical_grid_from_geotiff(geotiff_path, band=1):
    """
    Load a spherical grid from a GeoTIFF file.

    Args:
        geotiff_path: Path to GeoTIFF file
        band: Band number to read (1-indexed)

    Returns:
        Tuple of (data array, nodata value)
    """
    with rasterio.open(geotiff_path) as src:
        data = src.read(band)
        nodata = src.nodata if src.nodata is not None else -9999
    return data, nodata


def process_geotiff_file(geotiff_path, output_dir, size=1024, view='upper',
                         projection='equidistant', colormap='gray',
                         save_raw=False, band=1):
    """
    Process a single spherical grid GeoTIFF file to generate hemispherical image.

    Args:
        geotiff_path: Path to input GeoTIFF file
        output_dir: Output directory path
        size: Output image size (pixels)
        view: 'upper' or 'lower' hemisphere
        projection: 'equidistant' or 'equisolid'
        colormap: Matplotlib colormap name
        save_raw: Also save raw float32 numpy array
        band: Band number to process (1-indexed)

    Returns:
        Dictionary with processing results
    """
    try:
        geotiff_path = Path(geotiff_path)

        # Load spherical grid from GeoTIFF
        data, nodata = load_spherical_grid_from_geotiff(str(geotiff_path), band=band)

        # Convert to hemispherical projection
        hemi_img = spherical_to_hemispherical(
            data, size=size, view=view,
            projection=projection, nodata=nodata
        )

        # Colorize and save
        output_path = Path(output_dir)
        base_name = f"{geotiff_path.stem}_{view}"

        # Save PNG image
        pil_img = normalize_and_colorize(hemi_img, colormap=colormap)
        png_file = output_path / f"{base_name}_hemispherical.png"
        pil_img.save(png_file)

        # Optionally save raw data
        npy_file = None
        if save_raw:
            npy_file = output_path / f"{base_name}_hemispherical.npy"
            np.save(npy_file, hemi_img)

        return {
            'success': True,
            'input_file': str(geotiff_path),
            'png_file': str(png_file),
            'npy_file': str(npy_file) if npy_file else None,
            'valid_pixels': int(np.sum(~np.isnan(hemi_img))),
            'total_pixels': size * size
        }

    except Exception as e:
        return {
            'success': False,
            'input_file': str(geotiff_path),
            'error': str(e)
        }


def process_scan_position(scan_info, output_dir, resolution=0.5,
                          attribute='reflectance', size=1024,
                          view='upper', projection='equidistant',
                          colormap='gray', method='MEAN',
                          query_str=None, save_raw=False):
    """
    Process a single scan position to generate hemispherical image.

    Args:
        scan_info: Dictionary with scan file paths
        output_dir: Output directory path
        resolution: Angular resolution for spherical grid (degrees)
        attribute: Attribute to visualize
        size: Output image size (pixels)
        view: 'upper' or 'lower' hemisphere
        projection: 'equidistant' or 'equisolid'
        colormap: Matplotlib colormap name
        method: Grid aggregation method
        query_str: Optional point filter query
        save_raw: Also save raw float32 numpy array

    Returns:
        Dictionary with processing results
    """
    try:
        # Create spherical grid from scan data
        spherical_grid = create_spherical_grid(
            scan_info, resolution, attribute=attribute,
            method=method, query_str=query_str
        )

        if spherical_grid is None:
            return {
                'success': False,
                'scan_pos': scan_info['scan_pos'],
                'scan_name': scan_info['scan_name'],
                'error': 'Failed to create spherical grid'
            }

        # Convert to hemispherical projection
        hemi_img = spherical_to_hemispherical(
            spherical_grid, size=size, view=view,
            projection=projection
        )

        # Colorize and save
        output_path = Path(output_dir)
        base_name = f"{scan_info['scan_pos']}_{scan_info['scan_name']}_{attribute}_{view}"

        # Save PNG image
        pil_img = normalize_and_colorize(hemi_img, colormap=colormap)
        png_file = output_path / f"{base_name}_hemispherical.png"
        pil_img.save(png_file)

        # Optionally save raw data
        npy_file = None
        if save_raw:
            npy_file = output_path / f"{base_name}_hemispherical.npy"
            np.save(npy_file, hemi_img)

        return {
            'success': True,
            'scan_pos': scan_info['scan_pos'],
            'scan_name': scan_info['scan_name'],
            'png_file': str(png_file),
            'npy_file': str(npy_file) if npy_file else None,
            'valid_pixels': int(np.sum(~np.isnan(hemi_img))),
            'total_pixels': size * size
        }

    except Exception as e:
        return {
            'success': False,
            'scan_pos': scan_info['scan_pos'],
            'scan_name': scan_info['scan_name'],
            'error': str(e)
        }


def main():
    parser = argparse.ArgumentParser(
        description='Batch generate hemispherical images from TLS scans in a RISCAN project',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate upper hemisphere reflectance images from RISCAN project
  python batch_hemispherical_images.py /path/to/project.RiSCAN -o hemi_output

  # Generate lower hemisphere (looking down) with equisolid projection
  python batch_hemispherical_images.py /path/to/project.RiSCAN --view lower --projection equisolid

  # Generate range images with custom resolution and colormap
  python batch_hemispherical_images.py /path/to/project.RiSCAN --attribute range --resolution 0.25 --colormap viridis

  # Convert existing spherical grid GeoTIFF files to hemispherical images
  python batch_hemispherical_images.py --from-grids /path/to/grids/*.tif -o hemi_output

  # Convert a directory of GeoTIFF files
  python batch_hemispherical_images.py --from-grids /path/to/grids/ -o hemi_output
        """
    )
    parser.add_argument(
        'riscan_project',
        nargs='?',
        default=None,
        help='Path to RISCAN project directory (*.RiSCAN folder)'
    )
    parser.add_argument(
        '--from-grids',
        type=str,
        default=None,
        help='Process existing spherical grid GeoTIFF files instead of raw scans. '
             'Can be a directory path or glob pattern (e.g., "/path/*.tif")'
    )
    parser.add_argument(
        '-o', '--output',
        default='hemispherical_output',
        help='Output directory for images (default: hemispherical_output)'
    )
    parser.add_argument(
        '--resolution',
        type=float,
        default=0.5,
        help='Angular resolution for spherical grid in degrees (default: 0.5)'
    )
    parser.add_argument(
        '--attribute',
        type=str,
        default='reflectance',
        choices=['reflectance', 'range', 'intensity'],
        help='Attribute to visualize (default: reflectance)'
    )
    parser.add_argument(
        '--size',
        type=int,
        default=1024,
        help='Output image size in pixels (default: 1024)'
    )
    parser.add_argument(
        '--view',
        type=str,
        choices=['upper', 'lower'],
        default='upper',
        help='Hemisphere view: upper (looking up) or lower (looking down) (default: upper)'
    )
    parser.add_argument(
        '--projection',
        type=str,
        choices=['equidistant', 'equisolid'],
        default='equidistant',
        help='Projection type: equidistant or equisolid-angle (default: equidistant)'
    )
    parser.add_argument(
        '--colormap',
        type=str,
        default='gray',
        help='Matplotlib colormap name (default: gray)'
    )
    parser.add_argument(
        '--method',
        choices=['MEAN', 'MAX', 'MIN'],
        default='MEAN',
        help='Grid aggregation method (default: MEAN)'
    )
    parser.add_argument(
        '--reflectance-threshold',
        type=float,
        default=None,
        help='Minimum reflectance threshold for filtering points'
    )
    parser.add_argument(
        '--dat-dir',
        type=str,
        default=None,
        help='Optional custom directory containing .DAT transform files'
    )
    parser.add_argument(
        '--save-raw',
        action='store_true',
        help='Also save raw float32 numpy arrays'
    )
    parser.add_argument(
        '--skip-existing',
        action='store_true',
        help='Skip scans that already have output files'
    )

    args = parser.parse_args()

    # Validate input arguments
    if args.from_grids is None and args.riscan_project is None:
        parser.error("Either riscan_project or --from-grids must be provided")

    # Create output directory
    output_path = Path(args.output)
    output_path.mkdir(parents=True, exist_ok=True)

    results = []
    skipped = 0

    if args.from_grids is not None:
        # Mode 1: Process existing GeoTIFF files
        from_grids_path = Path(args.from_grids)

        if from_grids_path.is_dir():
            # Directory: find all .tif files
            geotiff_files = sorted(from_grids_path.glob("*.tif"))
        else:
            # Glob pattern
            geotiff_files = sorted([Path(f) for f in globlib.glob(args.from_grids)])

        if not geotiff_files:
            print(f"No GeoTIFF files found matching: {args.from_grids}")
            return 1

        print(f"Found {len(geotiff_files)} GeoTIFF files to process")

        for geotiff_path in tqdm(geotiff_files, desc="Generating hemispherical images"):
            # Check if output already exists
            if args.skip_existing:
                expected_output = output_path / f"{geotiff_path.stem}_{args.view}_hemispherical.png"
                if expected_output.exists():
                    skipped += 1
                    continue

            result = process_geotiff_file(
                geotiff_path,
                args.output,
                size=args.size,
                view=args.view,
                projection=args.projection,
                colormap=args.colormap,
                save_raw=args.save_raw
            )

            if not result['success']:
                print(f"\nError processing {result['input_file']}: {result['error']}")

            results.append(result)

    else:
        # Mode 2: Process RISCAN project
        print(f"Scanning RISCAN project: {args.riscan_project}")
        scan_positions = find_scan_positions(args.riscan_project)
        print(f"Found {len(scan_positions)} scan positions")

        # Get file paths for each scan position
        project_path = Path(args.riscan_project)
        scan_files = []
        for scan_pos in scan_positions:
            files = get_scan_files(scan_pos, project_path, dat_dir=args.dat_dir)
            if files:
                scan_files.append(files)
            else:
                print(f"Warning: Skipping {scan_pos.name} - missing required files")

        print(f"Processing {len(scan_files)} scans with valid file sets")

        # Build query string if threshold specified
        query_str = None
        if args.reflectance_threshold is not None:
            query_str = f'reflectance > {args.reflectance_threshold}'

        # Process each scan
        for scan_info in tqdm(scan_files, desc="Generating hemispherical images"):
            # Check if output already exists
            if args.skip_existing:
                expected_output = output_path / f"{scan_info['scan_pos']}_{scan_info['scan_name']}_{args.attribute}_{args.view}_hemispherical.png"
                if expected_output.exists():
                    skipped += 1
                    continue

            result = process_scan_position(
                scan_info,
                args.output,
                resolution=args.resolution,
                attribute=args.attribute,
                size=args.size,
                view=args.view,
                projection=args.projection,
                colormap=args.colormap,
                method=args.method,
                query_str=query_str,
                save_raw=args.save_raw
            )

            if not result['success']:
                print(f"\nError processing {result['scan_pos']}: {result['error']}")

            results.append(result)

    # Summary
    successful = [r for r in results if r['success']]
    failed = [r for r in results if not r['success']]
    print(f"\nProcessing complete: {len(successful)} successful, {len(failed)} failed, {skipped} skipped (existing)")

    if successful:
        print(f"Output images saved to: {args.output}")
        avg_coverage = np.mean([r['valid_pixels'] / r['total_pixels'] * 100 for r in successful])
        print(f"Average hemisphere coverage: {avg_coverage:.1f}%")

    if failed:
        print("\nFailed scans:")
        for r in failed:
            name = r.get('scan_pos', r.get('input_file', 'Unknown'))
            print(f"  {name}: {r.get('error', 'Unknown error')}")
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
