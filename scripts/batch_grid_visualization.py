#!/usr/bin/env python
"""
Batch generate grid visualizations for all scans in a RISCAN project folder.

This script processes all ScanPos directories in a RISCAN project and generates
visualizations of scan grids (return count, reflectance) using the RIEGL grid functions.
"""

import os
import sys
import argparse
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend for batch processing
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
from mpl_toolkits.axes_grid1 import make_axes_locatable
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


def save_riegl_grid(data, output_file, label='Range (m)', clim=[0,30], figsize=(16,10), nbins=10,
                    cmap='bone', nreturns=None, extend='max', nodata=-9999, extent=None,
                    xlabel=None, ylabel=None, facecolor='white', title=False, dpi=150):
    """
    Save a RIEGL grid visualization to file.

    Modified from visualize.plot_riegl_grid to save instead of show.
    """
    if nreturns is None:
        nreturns = data.shape[0]
    fig, ax = plt.subplots(ncols=1, nrows=nreturns, squeeze=False,
                           sharex=False, sharey=False, figsize=figsize)
    with plt.style.context('seaborn-v0_8-notebook'):
        for i in range(nreturns):
            ax[i,0].set_facecolor(facecolor)
            ax[i,0].set(adjustable='box', aspect='equal')
            ax[i,0].set(xlabel=xlabel, ylabel=ylabel)
            if title and nreturns > 1:
                ax[i,0].set_title(f'Return {i+1:d} (maximum {data.shape[0]:d})', fontsize=14)
            elif isinstance(title, str):
                ax[i,0].set_title(title, fontsize=14)
            if extent is None:
                ax[i,0].get_xaxis().set_visible(False)
                ax[i,0].get_yaxis().set_visible(False)
            tmp = np.ma.masked_equal(data[i], nodata)
            p = ax[i,0].imshow(tmp, interpolation='nearest', clim=clim,
                               cmap=plt.get_cmap(cmap, nbins),
                               vmin=clim[0], vmax=clim[1], extent=extent)
            divider = make_axes_locatable(ax[i,0])
            cax = divider.append_axes('right', size='2%', pad=0.05)
            cbar = fig.colorbar(p, label=label, cax=cax, extend=extend)
            cbar.ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=nbins))
    fig.tight_layout()
    fig.savefig(output_file, dpi=dpi, bbox_inches='tight')
    plt.close(fig)


def save_combined_grid(data, output_file, label='Range (m)', clim=[0,30], figsize=(12,8), nbins=10,
                       cmap='turbo', extend='max', nodata=-9999, extent=None,
                       xlabel=None, ylabel=None, facecolor='black', title=None, dpi=150):
    """
    Save a combined RIEGL grid visualization (all returns merged into single plot).

    Combines multiple returns by taking the first valid (non-nodata) value for each pixel,
    which represents the closest return to the scanner.

    Args:
        data: 3D array with shape (nreturns, rows, cols)
        output_file: Path to save the image
        label: Colorbar label
        clim: Color limits [min, max]
        figsize: Figure size (width, height)
        nbins: Number of colorbar bins
        cmap: Colormap name
        extend: Colorbar extend option
        nodata: No-data value
        extent: Image extent for axis labels
        xlabel, ylabel: Axis labels
        facecolor: Background color for no-data pixels
        title: Plot title
        dpi: Output resolution
    """
    # Combine all returns - take first valid value (closest return)
    combined = np.full(data.shape[1:], nodata, dtype=data.dtype)
    for i in range(data.shape[0]):
        mask = (combined == nodata) & (data[i] != nodata)
        combined[mask] = data[i][mask]

    fig, ax = plt.subplots(figsize=figsize)
    with plt.style.context('seaborn-v0_8-notebook'):
        ax.set_facecolor(facecolor)
        ax.set(adjustable='box', aspect='equal')
        ax.set(xlabel=xlabel, ylabel=ylabel)
        if title:
            ax.set_title(title, fontsize=14)
        if extent is None:
            ax.get_xaxis().set_visible(False)
            ax.get_yaxis().set_visible(False)

        # Mask nodata values (will show as facecolor/background)
        masked_data = np.ma.masked_equal(combined, nodata)

        p = ax.imshow(masked_data, interpolation='nearest',
                      cmap=plt.get_cmap(cmap, nbins),
                      vmin=clim[0], vmax=clim[1], extent=extent)

        divider = make_axes_locatable(ax)
        cax = divider.append_axes('right', size='2%', pad=0.05)
        cbar = fig.colorbar(p, label=label, cax=cax, extend=extend)
        cbar.ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=nbins))

    fig.tight_layout()
    fig.savefig(output_file, dpi=dpi, bbox_inches='tight')
    plt.close(fig)


def process_scan_position(scan_info, output_dir, grid_type='count', dpi=150, max_distance=100):
    """
    Process a single scan position to generate grid visualizations.

    Args:
        scan_info: Dictionary with scan file paths
        output_dir: Output directory for images
        grid_type: Type of grid to generate ('count', 'reflectance', 'distance', or 'all')
        dpi: Resolution for saved images
        max_distance: Maximum distance for color scale in distance grid

    Returns:
        Dictionary with processing results
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    results = {
        'success': True,
        'scan_pos': scan_info['scan_pos'],
        'scan_name': scan_info['scan_name'],
        'files_created': []
    }

    try:
        # Generate return count grid from RXP (combined into single plot)
        if grid_type in ('count', 'all'):
            count_grid = grid.grid_riegl_scan(
                scan_info['rxp_file'],
                attribute='target_count',
                driver='rxp'
            )

            count_output = output_path / f"{scan_info['scan_pos']}_{scan_info['scan_name']}_count.png"
            save_combined_grid(
                count_grid,
                count_output,
                label='Return Count',
                clim=[0, 5],
                figsize=(12, 8),
                nbins=5,
                cmap='YlOrRd',
                extend='max',
                facecolor='black',  # Gaps/misses shown as black
                extent=[1, count_grid.shape[2], 1, count_grid.shape[1]],
                xlabel='Scan Line',
                ylabel='Scan Line Index',
                title=f'{scan_info["scan_pos"]} - Return Count',
                dpi=dpi
            )
            results['files_created'].append(str(count_output))

        # Generate distance/range grid from RXP (colored by distance, black for misses)
        # All returns combined into single plot
        if grid_type in ('distance', 'all'):
            range_grid = grid.grid_riegl_scan(
                scan_info['rxp_file'],
                attribute='range',
                driver='rxp'
            )

            distance_output = output_path / f"{scan_info['scan_pos']}_{scan_info['scan_name']}_distance.png"
            save_combined_grid(
                range_grid,
                distance_output,
                label='Distance (m)',
                clim=[0, max_distance],
                figsize=(12, 8),
                nbins=10,
                cmap='turbo',
                extend='max',
                facecolor='black',  # Gaps/misses shown as black
                extent=[1, range_grid.shape[2], 1, range_grid.shape[1]],
                xlabel='Scan Line',
                ylabel='Scan Line Index',
                title=f'{scan_info["scan_pos"]} - Distance from Scanner',
                dpi=dpi
            )
            results['files_created'].append(str(distance_output))

        # Generate reflectance grid from RDBX (if available, combined into single plot)
        if grid_type in ('reflectance', 'all') and scan_info['rdbx_file']:
            reflectance_grid = grid.grid_riegl_scan(
                scan_info['rdbx_file'],
                attribute='reflectance',
                driver='rdbx'
            )

            reflectance_output = output_path / f"{scan_info['scan_pos']}_{scan_info['scan_name']}_reflectance.png"
            save_combined_grid(
                reflectance_grid,
                reflectance_output,
                label='Reflectance (dB)',
                clim=[-20, 5],
                figsize=(12, 8),
                nbins=10,
                cmap='turbo',
                extend='both',
                facecolor='black',  # Gaps/misses shown as black
                extent=[1, reflectance_grid.shape[2], 1, reflectance_grid.shape[1]],
                xlabel='Scan Line',
                ylabel='Scan Line Index',
                title=f'{scan_info["scan_pos"]} - Reflectance',
                dpi=dpi
            )
            results['files_created'].append(str(reflectance_output))

    except Exception as e:
        results['success'] = False
        results['error'] = str(e)

    return results


def main():
    parser = argparse.ArgumentParser(
        description='Batch generate grid visualizations for all scans in a RISCAN project'
    )
    parser.add_argument(
        'riscan_project',
        help='Path to RISCAN project directory (*.RiSCAN folder)'
    )
    parser.add_argument(
        '-o', '--output',
        default='grid_output',
        help='Output directory for images (default: grid_output)'
    )
    parser.add_argument(
        '--grid-type',
        choices=['count', 'reflectance', 'distance', 'all'],
        default='distance',
        help='Type of grid to generate: count, reflectance, distance (colored by range, black gaps), or all (default: distance)'
    )
    parser.add_argument(
        '--dpi',
        type=int,
        default=150,
        help='Resolution for saved images (default: 150)'
    )
    parser.add_argument(
        '--dat-dir',
        type=str,
        default=None,
        help='Optional custom directory containing .DAT transform files'
    )
    parser.add_argument(
        '--max-distance',
        type=float,
        default=100,
        help='Maximum distance for color scale in distance grid (default: 100m)'
    )
    parser.add_argument(
        '--skip-existing',
        action='store_true',
        help='Skip scans that already have output files'
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
        files = get_scan_files(scan_pos, project_path, dat_dir=args.dat_dir)
        if files:
            scan_files.append(files)
        else:
            print(f"Warning: Skipping {scan_pos.name} - missing required files")

    print(f"Processing {len(scan_files)} scans with valid file sets")

    # Create output directory
    output_path = Path(args.output)
    output_path.mkdir(parents=True, exist_ok=True)

    # Process each scan
    results = []
    skipped = 0
    for scan_info in tqdm(scan_files, desc="Generating visualizations"):
        # Check if output already exists
        if args.skip_existing:
            # Check for the primary output file based on grid_type
            if args.grid_type == 'all':
                check_file = output_path / f"{scan_info['scan_pos']}_{scan_info['scan_name']}_distance.png"
            else:
                check_file = output_path / f"{scan_info['scan_pos']}_{scan_info['scan_name']}_{args.grid_type}.png"
            if check_file.exists():
                skipped += 1
                continue

        result = process_scan_position(
            scan_info,
            args.output,
            grid_type=args.grid_type,
            dpi=args.dpi,
            max_distance=args.max_distance
        )

        if not result['success']:
            print(f"\nError processing {result['scan_pos']}: {result.get('error', 'Unknown error')}")

        results.append(result)

    # Summary
    successful = len([r for r in results if r['success']])
    failed = len([r for r in results if not r['success']])
    total_files = sum(len(r.get('files_created', [])) for r in results)

    print(f"\nProcessing complete: {successful} successful, {failed} failed, {skipped} skipped (existing)")
    print(f"Total images created: {total_files}")
    print(f"Output directory: {args.output}")

    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
