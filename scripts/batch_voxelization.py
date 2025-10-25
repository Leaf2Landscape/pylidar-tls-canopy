#!/usr/bin/env python
"""
Batch voxelization for all scans in a RISCAN project folder.

This script processes all ScanPos directories in a RISCAN project and generates
voxel-based models of directional gap probability (Pgap) and Plant Area Index (PAI).
"""

import os
import sys
import argparse
import json
from pathlib import Path
import glob
import numpy as np
from tqdm import tqdm

from pylidar_tls_canopy import voxelization, riegl_io


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


def get_scan_files(scan_pos_dir, project_path):
    """
    Get RXP, RDBX, and transform file paths for a scan position.

    Args:
        scan_pos_dir: Path to ScanPos directory
        project_path: Path to RISCAN project root

    Returns:
        Dictionary with rxp_file, rdbx_file, and transform_file paths
    """
    scan_pos_name = scan_pos_dir.name

    # Find RXP file in SCANS/ScanPosXXX/SINGLESCANS/
    singlescans_dir = scan_pos_dir / "SINGLESCANS"
    if not singlescans_dir.exists():
        return None

    # Get all singlescan directories and find the most recent one
    pattern = str(singlescans_dir / "??????_??????.rxp")
    rxp_files = glob.glob(pattern)
    if not rxp_files:
        return None

    rxp_file = max(rxp_files, key=os.path.getctime)
    scan_name = Path(rxp_file).stem

    # RDBX file in project.rdb/SCANS/ScanPosXXX/SINGLESCANS/scan_name/
    rdbx_file = project_path / "project.rdb" / "SCANS" / scan_pos_name / "SINGLESCANS" / scan_name / f"{scan_name}.rdbx"

    # Transform file - check multiple possible locations
    transform_file = None
    possible_locations = [
        project_path / "SCANS" / "matrix" / f"{scan_pos_name}.DAT",
        project_path / "project.rdb" / "SCANS" / f"{scan_pos_name}.DAT",
    ]

    for loc in possible_locations:
        if loc.exists():
            transform_file = loc
            break

    if transform_file is None:
        return None

    return {
        'rxp_file': str(rxp_file),
        'rdbx_file': str(rdbx_file) if rdbx_file.exists() else None,
        'transform_file': str(transform_file),
        'scan_name': scan_name,
        'scan_pos': scan_pos_name
    }


def compute_bounds(transform_files, buffer=5, hmax=50):
    """
    Compute voxelization bounds from scan positions.

    Args:
        transform_files: List of transform file paths
        buffer: Buffer to extend bounds (m)
        hmax: Maximum tree height (m)

    Returns:
        Array of bounds [xmin, ymin, zmin, xmax, ymax, zmax]
    """
    # xmin, ymin, zmin, xmax, ymax, zmax
    bounds = np.array([np.Inf, np.Inf, np.Inf, -np.Inf, -np.Inf, -np.Inf])

    for fn in transform_files:
        transform_matrix = riegl_io.read_transform_file(fn)
        x_tmp, y_tmp, z_tmp, _ = transform_matrix[3, :]
        bounds[0] = x_tmp if x_tmp < bounds[0] else bounds[0]
        bounds[1] = y_tmp if y_tmp < bounds[1] else bounds[1]
        bounds[2] = z_tmp if z_tmp < bounds[2] else bounds[2]
        bounds[3] = x_tmp if x_tmp > bounds[3] else bounds[3]
        bounds[4] = y_tmp if y_tmp > bounds[4] else bounds[4]
        bounds[5] = z_tmp if z_tmp > bounds[5] else bounds[5]

    # Round and extend bounds
    bounds[0:3] = (bounds[0:3] - buffer) // buffer * buffer
    bounds[3:6] = (bounds[3:6] + 1.5 * buffer) // buffer * buffer
    bounds[2] -= buffer
    bounds[5] += hmax

    return bounds


def process_scan_position(scan_info, bounds, voxelsize, dtm_filename=None,
                         save_counts=True):
    """
    Process a single scan position to generate voxel grids.

    Args:
        scan_info: Dictionary with scan file paths
        bounds: Voxelization bounds [xmin, ymin, zmin, xmax, ymax, zmax]
        voxelsize: Voxel resolution (m)
        dtm_filename: Optional DTM file path
        save_counts: Save hit/miss/occluded counts

    Returns:
        Dictionary with voxel grid filenames
    """
    try:
        # Initialize voxel grid
        vgrid = voxelization.VoxelGrid(dtm_filename=dtm_filename)

        # Add scan position (use RDBX if available, otherwise RXP only)
        vgrid.add_riegl_scan_position(
            scan_info['rxp_file'],
            scan_info['transform_file'],
            rdbx_file=scan_info['rdbx_file']
        )

        # Voxelize scan
        vgrid.voxelize_scan(bounds, voxelsize, save_counts=save_counts)

        return {
            'success': True,
            'scan_pos': scan_info['scan_pos'],
            'scan_name': scan_info['scan_name'],
            'vgrid': vgrid
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
        description='Batch voxelization for all scans in a RISCAN project'
    )
    parser.add_argument(
        'riscan_project',
        help='Path to RISCAN project directory (*.RiSCAN folder)'
    )
    parser.add_argument(
        '-o', '--output',
        default='voxel_output',
        help='Output directory for voxel grids (default: voxel_output)'
    )
    parser.add_argument(
        '--voxelsize',
        type=float,
        default=1.0,
        help='Voxel grid resolution in meters (default: 1.0)'
    )
    parser.add_argument(
        '--buffer',
        type=float,
        default=5,
        help='Buffer to extend voxel bounds in meters (default: 5)'
    )
    parser.add_argument(
        '--hmax',
        type=float,
        default=50,
        help='Maximum tree height in meters (default: 50)'
    )
    parser.add_argument(
        '--dtm',
        type=str,
        default=None,
        help='Path to DTM file (optional, must be in same coordinate system as TLS)'
    )
    parser.add_argument(
        '--no-counts',
        action='store_true',
        help='Do not save hit/miss/occluded count grids'
    )
    parser.add_argument(
        '--min-n',
        type=int,
        default=3,
        help='Minimum number of Pgap observations required to estimate PAI (default: 3)'
    )
    parser.add_argument(
        '--run-model',
        action='store_true',
        help='Run the linear model to derive PAI and cover profiles after voxelization'
    )
    parser.add_argument(
        '--weighted',
        action='store_true',
        help='Use weighted linear model (applies when --run-model is set)'
    )

    args = parser.parse_args()

    # Create output directory
    output_path = Path(args.output)
    output_path.mkdir(parents=True, exist_ok=True)

    # Find all scan positions
    print(f"Scanning RISCAN project: {args.riscan_project}")
    scan_positions = find_scan_positions(args.riscan_project)
    print(f"Found {len(scan_positions)} scan positions")

    # Get file paths for each scan position
    project_path = Path(args.riscan_project)
    scan_files = []
    transform_files = []

    for scan_pos in scan_positions:
        files = get_scan_files(scan_pos, project_path)
        if files:
            scan_files.append(files)
            transform_files.append(files['transform_file'])
        else:
            print(f"Warning: Skipping {scan_pos.name} - missing required files")

    print(f"Processing {len(scan_files)} scans with valid file sets")

    # Compute bounds from all scan positions
    print("Computing voxelization bounds...")
    bounds = compute_bounds(transform_files, buffer=args.buffer, hmax=args.hmax)
    print(f"Bounds: xmin={bounds[0]:.1f}, ymin={bounds[1]:.1f}, zmin={bounds[2]:.1f}, "
          f"xmax={bounds[3]:.1f}, ymax={bounds[4]:.1f}, zmax={bounds[5]:.1f}")

    # Initialize config for multi-scan processing
    config = {
        'bounds': bounds.tolist(),
        'resolution': args.voxelsize,
        'nx': int((bounds[3] - bounds[0]) // args.voxelsize),
        'ny': int((bounds[4] - bounds[1]) // args.voxelsize),
        'nz': int((bounds[5] - bounds[2]) // args.voxelsize),
        'nodata': -9999,
        'dtm': args.dtm,
        'positions': {}
    }

    # Process each scan
    print("\nVoxelizing scans...")
    results = []

    for scan_info in tqdm(scan_files, desc="Processing scans"):
        result = process_scan_position(
            scan_info,
            bounds,
            args.voxelsize,
            dtm_filename=args.dtm,
            save_counts=not args.no_counts
        )

        if not result['success']:
            print(f"\nError processing {result['scan_pos']}: {result['error']}")
            results.append(result)
            continue

        # Write voxel grids for this scan
        vgrid = result['vgrid']
        prefix = str(output_path / f"{result['scan_name']}")
        vgrid.write_grids(prefix)

        # Store filenames in config
        config['positions'][result['scan_name']] = vgrid.filenames

        results.append(result)

    # Save configuration file
    config_file = output_path / f"{project_path.stem}_config.json"
    with open(config_file, 'w') as f:
        json.dump(config, indent=4, fp=f)

    print(f"\nSaved configuration to {config_file}")

    # Summary
    successful = len([r for r in results if r['success']])
    failed = len([r for r in results if not r['success']])
    print(f"\nVoxelization complete: {successful} successful, {failed} failed")

    # Run multi-scan model if requested
    if args.run_model and successful > 0:
        print("\nRunning linear model to derive PAI and cover profiles...")

        try:
            vmodel = voxelization.VoxelModel(str(config_file))
            paiv, paih, nscans = vmodel.run_linear_model(
                min_n=args.min_n,
                weights=args.weighted
            )
            cover_z = vmodel.get_cover_profile(paiv)

            # Save model outputs
            model_output = output_path / "model_output"
            model_output.mkdir(exist_ok=True)

            np.save(model_output / "paiv.npy", paiv)
            np.save(model_output / "paih.npy", paih)
            np.save(model_output / "nscans.npy", nscans)
            np.save(model_output / "cover_z.npy", cover_z)

            print(f"Saved model outputs to {model_output}")
            print(f"  PAI vertical shape: {paiv.shape}")
            print(f"  PAI horizontal shape: {paih.shape}")
            print(f"  Cover profile shape: {cover_z.shape}")

        except Exception as e:
            print(f"Error running model: {e}")
            return 1

    if successful == 0:
        print("No scans voxelized successfully")
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
