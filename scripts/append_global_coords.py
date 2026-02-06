#!/usr/bin/env python
"""
Script to append global coordinates from DAT_GLOBAL files to PAVD summary CSV.
"""
import csv
import os

# Paths
dat_global_dir = "/scratch/project/veg3d/TERN_TLS_DATA/raw_data/RobsonCreek.RiSCAN/DAT_GLOBAL"
pavd_summary_path = "/scratch/project/veg3d/uqtdeve1/code/pylidar-tls-canopy/scripts/pavd_output/pavd_summary.csv"

def read_dat_global(dat_file):
    """
    Read a DAT file and extract global X, Y, Z coordinates.
    The DAT file contains a 4x4 transformation matrix where the last column
    contains the translation (global coordinates).

    Returns:
        tuple: (global_x, global_y, global_z)
    """
    with open(dat_file, 'r') as f:
        lines = f.readlines()

    # Parse the matrix
    # Line 0: row 0 of matrix, last value is global X
    # Line 1: row 1 of matrix, last value is global Y
    # Line 2: row 2 of matrix, last value is global Z
    global_x = float(lines[0].strip().split()[-1])
    global_y = float(lines[1].strip().split()[-1])
    global_z = float(lines[2].strip().split()[-1])

    return global_x, global_y, global_z

# Read the PAVD summary CSV
print(f"Reading {pavd_summary_path}")
with open(pavd_summary_path, 'r') as f:
    reader = csv.DictReader(f)
    rows = list(reader)
    fieldnames = reader.fieldnames

# Add new columns to fieldnames
new_fieldnames = list(fieldnames) + ['global_x', 'global_y', 'global_z']

# Process each scan position
found_count = 0
for row in rows:
    scan_pos = row['scan_pos']
    dat_file = os.path.join(dat_global_dir, f"{scan_pos}.DAT")

    if os.path.exists(dat_file):
        try:
            global_x, global_y, global_z = read_dat_global(dat_file)
            row['global_x'] = global_x
            row['global_y'] = global_y
            row['global_z'] = global_z
            found_count += 1
            print(f"  {scan_pos}: X={global_x:.3f}, Y={global_y:.3f}, Z={global_z:.3f}")
        except Exception as e:
            print(f"  Error reading {dat_file}: {e}")
            row['global_x'] = ''
            row['global_y'] = ''
            row['global_z'] = ''
    else:
        print(f"  Warning: {dat_file} not found")
        row['global_x'] = ''
        row['global_y'] = ''
        row['global_z'] = ''

# Save the updated CSV
output_path = os.path.join(os.path.dirname(pavd_summary_path), "pavd_summary_with_global.csv")
with open(output_path, 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=new_fieldnames)
    writer.writeheader()
    writer.writerows(rows)
print(f"\nSaved updated summary to: {output_path}")

# Also update the original file
with open(pavd_summary_path, 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=new_fieldnames)
    writer.writeheader()
    writer.writerows(rows)
print(f"Updated original file: {pavd_summary_path}")

print(f"\nAdded columns: global_x, global_y, global_z")
print(f"Total scan positions processed: {len(rows)}")
print(f"Scan positions with global coords: {found_count}")
