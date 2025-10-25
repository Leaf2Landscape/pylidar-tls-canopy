#!/usr/bin/env python
"""
Batch process PAVD profiles for all scans in a RISCAN project folder.

This script processes all ScanPos directories in a RISCAN project and generates
vertical Plant Area Volume Density (PAVD) profiles using the Jupp et al. (2009) method.
"""

import os
import sys
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
from tqdm import tqdm

from pylidar_tls_canopy import riegl_io, plant_profile


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

    # Transform file - check both standard location and DAT directory
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


def process_scan_position(scan_info, hres=0.5, zres=5, ares=90,
                         min_z=35, max_z=70, min_h=0, max_h=50,
                         reflectance_threshold=-20, method='WEIGHTED'):
    """
    Process a single scan position to generate PAVD profiles.

    Args:
        scan_info: Dictionary with scan file paths
        hres: Vertical height bin resolution (m)
        zres: Zenith angle bin resolution (degrees)
        ares: Azimuth angle bin resolution (degrees)
        min_z: Minimum zenith angle (degrees)
        max_z: Maximum zenith angle (degrees)
        min_h: Minimum height (m)
        max_h: Maximum height (m)
        reflectance_threshold: Minimum reflectance value
        method: Pgap estimation method (WEIGHTED, FIRST, or ALL)

    Returns:
        Dictionary with profile results
    """
    # Read transform to get sensor position
    transform_matrix = riegl_io.read_transform_file(scan_info['transform_file'])
    x0, y0, z0, _ = transform_matrix[3, :]

    # Fit ground plane
    grid_extent = 60
    grid_resolution = 10
    grid_origin = [x0, y0]

    try:
        # Use RDBX if available, otherwise RXP only
        rxp_mode = scan_info['rdbx_file'] is None or not os.path.exists(scan_info['rdbx_file'])

        if rxp_mode:
            files = [scan_info['rxp_file']]
        else:
            files = [scan_info['rdbx_file']]

        transforms = [scan_info['transform_file']]

        # Get minimum Z grid for ground plane fitting
        x, y, z, r = plant_profile.get_min_z_grid(
            files, transforms,
            grid_extent, grid_resolution,
            grid_origin=grid_origin,
            rxp=rxp_mode
        )

        # Fit ground plane using Huber's method
        planefit = plant_profile.plane_fit_hubers(x, y, z, w=1/r)

        # Initialize vertical plant profile
        vpp = plant_profile.Jupp2009(
            hres=hres, zres=zres, ares=ares,
            min_z=min_z, max_z=max_z,
            min_h=min_h, max_h=max_h,
            ground_plane=planefit['Parameters']
        )

        # Add scan position with reflectance filter
        query_str = [f'reflectance > {reflectance_threshold}']

        vpp.add_riegl_scan_position(
            scan_info['rxp_file'],
            scan_info['transform_file'],
            sensor_height=None,
            rdbx_file=scan_info['rdbx_file'] if not rxp_mode else None,
            method=method,
            min_zenith=min_z,
            max_zenith=max_z,
            query_str=query_str
        )

        # Compute Pgap by zenith bin
        vpp.get_pgap_theta_z()

        # Calculate plant profiles using all three methods
        hinge_pai = vpp.calcHingePlantProfiles()
        weighted_pai = vpp.calcSolidAnglePlantProfiles()
        linear_pai, linear_mla = vpp.calcLinearPlantProfiles(calc_mla=True)

        # Convert to PAVD
        hinge_pavd = vpp.get_pavd(hinge_pai)
        linear_pavd = vpp.get_pavd(linear_pai)
        weighted_pavd = vpp.get_pavd(weighted_pai)

        return {
            'success': True,
            'scan_pos': scan_info['scan_pos'],
            'scan_name': scan_info['scan_name'],
            'sensor_position': [x0, y0, z0],
            'ground_plane': planefit['Parameters'],
            'height_bin': vpp.height_bin,
            'pgap_theta_z': vpp.pgap_theta_z,
            'hinge_pai': hinge_pai,
            'linear_pai': linear_pai,
            'weighted_pai': weighted_pai,
            'hinge_pavd': hinge_pavd,
            'linear_pavd': linear_pavd,
            'weighted_pavd': weighted_pavd,
            'linear_mla': linear_mla,
            'total_pai_hinge': np.sum(hinge_pai) * hres,
            'total_pai_linear': np.sum(linear_pai) * hres,
            'total_pai_weighted': np.sum(weighted_pai) * hres,
        }

    except Exception as e:
        return {
            'success': False,
            'scan_pos': scan_info['scan_pos'],
            'scan_name': scan_info['scan_name'],
            'error': str(e)
        }


def save_results(results, output_dir):
    """
    Save processing results to CSV files.

    Args:
        results: List of result dictionaries
        output_dir: Output directory path
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Save summary statistics
    summary_data = []
    for result in results:
        if result['success']:
            summary_data.append({
                'scan_pos': result['scan_pos'],
                'scan_name': result['scan_name'],
                'sensor_x': result['sensor_position'][0],
                'sensor_y': result['sensor_position'][1],
                'sensor_z': result['sensor_position'][2],
                'ground_intercept': result['ground_plane'][0],
                'ground_slope_x': result['ground_plane'][1],
                'ground_slope_y': result['ground_plane'][2],
                'total_pai_hinge': result['total_pai_hinge'],
                'total_pai_linear': result['total_pai_linear'],
                'total_pai_weighted': result['total_pai_weighted'],
            })

    if summary_data:
        summary_df = pd.DataFrame(summary_data)
        summary_df.to_csv(output_path / 'pavd_summary.csv', index=False)
        print(f"\nSaved summary to {output_path / 'pavd_summary.csv'}")

    # Save detailed profiles for each successful scan
    for result in results:
        if result['success']:
            scan_pos = result['scan_pos']

            # Create DataFrame with height bins and all profile types
            profile_df = pd.DataFrame({
                'height': result['height_bin'],
                'hinge_pai': result['hinge_pai'],
                'linear_pai': result['linear_pai'],
                'weighted_pai': result['weighted_pai'],
                'hinge_pavd': result['hinge_pavd'],
                'linear_pavd': result['linear_pavd'],
                'weighted_pavd': result['weighted_pavd'],
                'linear_mla': result['linear_mla'],
            })

            profile_file = output_path / f'{scan_pos}_{result["scan_name"]}_profiles.csv'
            profile_df.to_csv(profile_file, index=False)

    print(f"Saved {len([r for r in results if r['success']])} detailed profile files to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Batch process PAVD profiles for all scans in a RISCAN project'
    )
    parser.add_argument(
        'riscan_project',
        help='Path to RISCAN project directory (*.RiSCAN folder)'
    )
    parser.add_argument(
        '-o', '--output',
        default='pavd_output',
        help='Output directory for results (default: pavd_output)'
    )
    parser.add_argument(
        '--hres',
        type=float,
        default=0.5,
        help='Vertical height bin resolution in meters (default: 0.5)'
    )
    parser.add_argument(
        '--zres',
        type=float,
        default=5,
        help='Zenith angle bin resolution in degrees (default: 5)'
    )
    parser.add_argument(
        '--ares',
        type=float,
        default=90,
        help='Azimuth angle bin resolution in degrees (default: 90)'
    )
    parser.add_argument(
        '--min-zenith',
        type=float,
        default=35,
        help='Minimum zenith angle in degrees (default: 35)'
    )
    parser.add_argument(
        '--max-zenith',
        type=float,
        default=70,
        help='Maximum zenith angle in degrees (default: 70)'
    )
    parser.add_argument(
        '--min-height',
        type=float,
        default=0,
        help='Minimum height in meters (default: 0)'
    )
    parser.add_argument(
        '--max-height',
        type=float,
        default=50,
        help='Maximum height in meters (default: 50)'
    )
    parser.add_argument(
        '--reflectance-threshold',
        type=float,
        default=-20,
        help='Minimum reflectance threshold (default: -20)'
    )
    parser.add_argument(
        '--method',
        choices=['WEIGHTED', 'FIRST', 'ALL'],
        default='WEIGHTED',
        help='Pgap estimation method (default: WEIGHTED)'
    )

    args = parser.parse_args()

    # Find all scan positions
    print(f"Scanning RISCAN project: {args.riscan_project}")
    scan_positions = find_scan_positions(args.riscan_project)
    print(f"Found {len(scan_positions)} scan positions")

    # Get file paths for each scan position
    project_path = Path(args.riscan_project)
    scan_files = []
    for scan_pos in scan_positions:
        files = get_scan_files(scan_pos, project_path)
        if files:
            scan_files.append(files)
        else:
            print(f"Warning: Skipping {scan_pos.name} - missing required files")

    print(f"Processing {len(scan_files)} scans with valid file sets")

    # Process each scan
    results = []
    for scan_info in tqdm(scan_files, desc="Processing scans"):
        result = process_scan_position(
            scan_info,
            hres=args.hres,
            zres=args.zres,
            ares=args.ares,
            min_z=args.min_zenith,
            max_z=args.max_zenith,
            min_h=args.min_height,
            max_h=args.max_height,
            reflectance_threshold=args.reflectance_threshold,
            method=args.method
        )

        if not result['success']:
            print(f"\nError processing {result['scan_pos']}: {result['error']}")

        results.append(result)

    # Save results
    successful = len([r for r in results if r['success']])
    failed = len([r for r in results if not r['success']])
    print(f"\nProcessing complete: {successful} successful, {failed} failed")

    if successful > 0:
        save_results(results, args.output)
    else:
        print("No scans processed successfully")
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
