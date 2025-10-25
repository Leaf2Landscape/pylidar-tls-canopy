# Batch Processing Scripts for RISCAN Projects

This directory contains batch processing scripts for RIEGL RISCAN projects.

## Scripts

1. **batch_pavd_profiles.py** - Generate PAVD profiles for all scans
2. **batch_voxelization.py** - Create voxel-based models for all scans

---

# Batch PAVD Profile Processing Script

This script processes all scans within a RIEGL RISCAN project folder and generates Plant Area Volume Density (PAVD) profiles using the Jupp et al. (2009) method.

## Requirements

- pylidar-tls-canopy package installed
- RIEGL RISCAN project with `.RiSCAN` folder structure
- Required files per scan position:
  - RXP file (raw scan data)
  - RDBX file (MTA corrected point cloud, optional but recommended for VZ400i+)
  - Transform file (`.DAT` file with scan position transformation matrix)

## Usage

### Basic Usage

Process all scans in a RISCAN project with default parameters:

```bash
python scripts/batch_pavd_profiles.py /path/to/project.RiSCAN
```

### Specify Output Directory

```bash
python scripts/batch_pavd_profiles.py /path/to/project.RiSCAN -o /path/to/output
```

### Advanced Options

```bash
python scripts/batch_pavd_profiles.py /path/to/project.RiSCAN \
    --output pavd_results \
    --hres 1.0 \
    --zres 5 \
    --ares 90 \
    --min-zenith 35 \
    --max-zenith 70 \
    --min-height 0 \
    --max-height 50 \
    --reflectance-threshold -20 \
    --method WEIGHTED
```

## Command-Line Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `riscan_project` | Path to RISCAN project directory (positional, required) | - |
| `-o, --output` | Output directory for results | `pavd_output` |
| `--hres` | Vertical height bin resolution (m) | 0.5 |
| `--zres` | Zenith angle bin resolution (degrees) | 5 |
| `--ares` | Azimuth angle bin resolution (degrees) | 90 |
| `--min-zenith` | Minimum zenith angle (degrees) | 35 |
| `--max-zenith` | Maximum zenith angle (degrees) | 70 |
| `--min-height` | Minimum height (m) | 0 |
| `--max-height` | Maximum height (m) | 50 |
| `--reflectance-threshold` | Minimum reflectance threshold | -20 |
| `--method` | Pgap estimation method (WEIGHTED/FIRST/ALL) | WEIGHTED |

## Output Files

The script generates the following output files:

### 1. Summary File (`pavd_summary.csv`)

Contains one row per successfully processed scan with:
- `scan_pos`: Scan position name (e.g., ScanPos001)
- `scan_name`: Scan timestamp name
- `sensor_x`, `sensor_y`, `sensor_z`: Sensor position coordinates
- `ground_intercept`, `ground_slope_x`, `ground_slope_y`: Ground plane parameters
- `total_pai_hinge`, `total_pai_linear`, `total_pai_weighted`: Total Plant Area Index

### 2. Detailed Profile Files (`ScanPosXXX_YYMMDD_HHMMSS_profiles.csv`)

One file per scan containing height-binned profiles:
- `height`: Height above ground (m)
- `hinge_pai`: PAI using hinge method
- `linear_pai`: PAI using linear method
- `weighted_pai`: PAI using solid angle weighted method
- `hinge_pavd`: PAVD using hinge method (m²/m³)
- `linear_pavd`: PAVD using linear method (m²/m³)
- `weighted_pavd`: PAVD using solid angle weighted method (m²/m³)
- `linear_mla`: Mean Leaf Angle from linear method (degrees)

## RISCAN Project Structure

The script expects the following RISCAN project structure:

```
project.RiSCAN/
├── SCANS/
│   ├── ScanPos001/
│   │   └── SINGLESCANS/
│   │       └── YYMMDD_HHMMSS/
│   │           └── YYMMDD_HHMMSS.rxp
│   ├── ScanPos002/
│   └── ...
└── project.rdb/
    └── SCANS/
        ├── ScanPos001/
        │   └── SINGLESCANS/
        │       └── YYMMDD_HHMMSS/
        │           └── YYMMDD_HHMMSS.rdbx
        ├── ScanPos001.DAT
        ├── ScanPos002.DAT
        └── ...
```

## Processing Notes

1. **Ground Plane Estimation**: Each scan is processed independently with automatic ground plane fitting using the Huber's robust method from Calders et al. (2014).

2. **Reflectance Filtering**: Points with reflectance values below the threshold are excluded from processing.

3. **Zenith Angle Range**: The default 35-70° range avoids incomplete sampling near horizontal and reduces variance from high zenith angles.

4. **RDBX vs RXP**:
   - If RDBX files are available (VZ400i and later with MTA correction), they are used for point positions
   - RXP files are always required for pulse/return information
   - For VZ400 or pulse rate ≤300kHz, RXP-only mode works fine

5. **Error Handling**: Scans that fail to process are logged with error messages, and processing continues with remaining scans.

## Example

Process a RISCAN project with custom height range for tall forest:

```bash
python scripts/batch_pavd_profiles.py \
    ~/LSS_2021_07_core.RiSCAN/LSS_2021_07_core.RiSCAN \
    -o lss_pavd_output \
    --max-height 80 \
    --hres 0.5
```

This will:
- Process all valid scan positions in the project
- Generate profiles up to 80m height with 0.5m bins
- Save results to `lss_pavd_output/` directory

## References

- Jupp, D. L. B., et al. (2009). Estimating forest LAI profiles and structural parameters using a ground-based laser called 'Echidna'. Tree Physiology, 29(2), 171-181.
- Calders, K., et al. (2014). Monitoring spring phenology with high temporal resolution terrestrial LiDAR measurements. Agricultural and Forest Meteorology, 203, 158-168.

---

# Batch Voxelization Script

This script processes all scans within a RIEGL RISCAN project folder and generates voxel-based models of directional gap probability (Pgap) and Plant Area Index (PAI).

## Requirements

- pylidar-tls-canopy package installed
- RIEGL RISCAN project with `.RiSCAN` folder structure
- Required files per scan position:
  - RXP file (raw scan data)
  - RDBX file (MTA corrected point cloud, optional but recommended for VZ400i+)
  - Transform file (`.DAT` file with scan position transformation matrix)
- Optional: DTM file in same coordinate system as TLS data

## Usage

### Basic Usage

Voxelize all scans in a RISCAN project with default parameters:

```bash
python scripts/batch_voxelization.py /path/to/project.RiSCAN
```

### Specify Output Directory and Voxel Size

```bash
python scripts/batch_voxelization.py /path/to/project.RiSCAN \
    -o voxel_output \
    --voxelsize 1.0
```

### With DTM and Model Processing

```bash
python scripts/batch_voxelization.py /path/to/project.RiSCAN \
    -o voxel_output \
    --voxelsize 1.0 \
    --dtm /path/to/dtm.tif \
    --run-model \
    --min-n 3
```

### Advanced Options

```bash
python scripts/batch_voxelization.py /path/to/project.RiSCAN \
    --output voxel_results \
    --voxelsize 0.5 \
    --buffer 10 \
    --hmax 60 \
    --dtm /path/to/local_dtm.tif \
    --run-model \
    --weighted \
    --min-n 3 \
    --no-counts
```

## Command-Line Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `riscan_project` | Path to RISCAN project directory (positional, required) | - |
| `-o, --output` | Output directory for voxel grids | `voxel_output` |
| `--voxelsize` | Voxel grid resolution (m) | 1.0 |
| `--buffer` | Buffer to extend voxel bounds (m) | 5 |
| `--hmax` | Maximum tree height (m) | 50 |
| `--dtm` | Path to DTM file (optional) | None |
| `--no-counts` | Do not save hit/miss/occluded count grids | False |
| `--min-n` | Minimum Pgap observations for PAI estimation | 3 |
| `--run-model` | Run linear model to derive PAI and cover | False |
| `--weighted` | Use weighted linear model | False |

## Output Files

### Per-Scan Voxel Grids (GeoTIFF format)

For each scan, the following 3D voxel grids are saved as multi-band GeoTIFF files:

- `{scan_name}_pgap.tif` - Gap probability per voxel
- `{scan_name}_vcls.tif` - Voxel class (1=ground, 2=canopy, etc.)
- `{scan_name}_vwts.tif` - Total path length through voxel
- `{scan_name}_zeni.tif` - Zenith angle

If `--no-counts` is not set, also saves:
- `{scan_name}_hits.tif` - Hit counts per voxel
- `{scan_name}_miss.tif` - Miss counts per voxel
- `{scan_name}_occl.tif` - Occluded counts per voxel

### Configuration File

- `{project_name}_config.json` - Configuration file with voxelization parameters and file paths for all scans

### Model Outputs (if `--run-model` is set)

In `model_output/` subdirectory:
- `paiv.npy` - Vertical Plant Area Index (3D array)
- `paih.npy` - Horizontal Plant Area Index (3D array)
- `nscans.npy` - Number of scans observing each voxel (3D array)
- `cover_z.npy` - Vertical canopy cover profile (3D array)

## RISCAN Project Structure

Same structure as required for batch_pavd_profiles.py (see above).

## Processing Notes

1. **Voxel Bounds**: Automatically computed from all scan positions with specified buffer and maximum height.

2. **Voxel Grid**: 3D grid aligned with local coordinate system. Each voxel contains:
   - Pgap: Gap probability from multiple view angles
   - Path length: Total beam path through voxel
   - Hit/miss/occluded counts (if saved)
   - Classification information

3. **Multi-Scan Model**: When `--run-model` is set, combines observations from all scans using linear inversion to estimate:
   - PAI vertical (foliage density in vertical direction)
   - PAI horizontal (foliage density in horizontal direction)
   - Canopy cover profile

4. **DTM Integration**: If a DTM is provided, it's used to:
   - Classify ground voxels
   - Improve height above ground calculations
   - Better separate canopy from ground returns

5. **Memory Requirements**: Large projects with fine voxel resolution can require significant memory. Consider:
   - Coarser voxel size for large areas
   - Using `--no-counts` to reduce memory usage
   - Processing subsets of scans if needed

## Example

Process a RISCAN project with fine voxel resolution and generate PAI model:

```bash
python scripts/batch_voxelization.py \
    ~/LSS_2021_07_core.RiSCAN/LSS_2021_07_core.RiSCAN \
    -o lss_voxel_output \
    --voxelsize 0.5 \
    --hmax 80 \
    --buffer 10 \
    --run-model \
    --min-n 3
```

This will:
- Voxelize all scan positions at 0.5m resolution
- Use bounds extended 10m beyond scan positions
- Account for trees up to 80m tall
- Combine scans to derive PAI (requiring ≥3 observations per voxel)
- Save individual voxel grids and combined model outputs

## Use Cases

1. **3D Forest Structure**: Detailed 3D mapping of canopy structure and gaps
2. **Validation**: Compare with airborne lidar or satellite data
3. **Simulations**: Input for radiative transfer models or waveform simulators
4. **Multi-Scale Analysis**: Link ground-based to airborne observations

## References

- Jupp, D. L. B., et al. (2009). Estimating forest LAI profiles and structural parameters using a ground-based laser called 'Echidna'. Tree Physiology, 29(2), 171-181.
- Hancock, S., et al. (2019). The GEDI simulator: A large-footprint waveform lidar simulator for calibration and validation of spaceborne missions. Earth and Space Science, 6(2), 294-310.
