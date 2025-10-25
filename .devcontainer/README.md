# Development Container Configuration

This directory contains the VS Code devcontainer configuration for pylidar-tls-canopy development.

## Prerequisites

1. **VS Code** with the "Dev Containers" extension installed
2. **Docker** installed and running
3. **RIEGL Libraries** (optional, for full functionality):
   - Place `rivlib-2_6_0-x86_64-linux-gcc11.zip` in `riegl_libs/` directory
   - Place `rdblib-2.4.1-x86_64-linux.tar.gz` in `riegl_libs/` directory

## Quick Start

1. Open this repository in VS Code
2. Press `F1` and select "Dev Containers: Reopen in Container"
3. Wait for the container to build and start (first time may take 5-10 minutes)
4. The environment will be ready with:
   - All Python dependencies installed
   - RIEGL libraries configured (if present)
   - Package installed in editable mode

## What's Included

### Base Image
- Ubuntu 22.04 (Jammy) with micromamba
- System tools: git, vim, curl, build-essential

### Python Environment
- Python 3.12
- All dependencies from `environment.yml`:
  - numpy, pandas, scipy
  - numba, rasterio
  - matplotlib, jupyterlab
  - And more...

### RIEGL Libraries
If the library archives are present in the `riegl_libs/` directory:
- RiVLib 2.6.0 (x86_64-linux-gcc11)
- RDBLib 2.4.1 (x86_64-linux)

These are automatically extracted and configured on first container creation.

### VS Code Extensions
Automatically installed:
- Python
- Pylance
- Jupyter
- Jupyter Keymap
- Jupyter Renderers

## Usage

### Running Scripts

```bash
# Activate conda environment (automatic in integrated terminal)
micromamba activate pylidar-tls-canopy

# Run batch processing scripts
python scripts/batch_pavd_profiles.py /path/to/data
python scripts/batch_voxelization.py /path/to/data
```

### Running Jupyter Notebooks

```bash
# Start JupyterLab
micromamba run -n pylidar-tls-canopy jupyter lab --ip=0.0.0.0 --no-browser
```

Or use VS Code's built-in Jupyter support to open `.ipynb` files directly.

### Development

The package is installed in editable mode (`pip install -e .`), so changes to the source code are immediately available.

```bash
# Run tests
python -m pytest

# Rebuild C extensions if needed
micromamba run -n pylidar-tls-canopy pip install -e . -v --force-reinstall --no-deps
```

## Container Details

### File Structure
```
/workspace/          # Repository root (mounted from host)
/opt/riegl/          # RIEGL libraries
  ├── rivlib/
  │   └── current/   # Symlink to extracted RiVLib
  └── rdblib/
      └── current/   # Symlink to extracted RDBLib
/opt/conda/envs/     # Conda environments
  └── pylidar-tls-canopy/
```

### Environment Variables
```bash
RIVLIB_ROOT=/opt/riegl/rivlib/current
RDBLIB_ROOT=/opt/riegl/rdblib/current
PYLIDAR_CXX_FLAGS=-std=c++11
LD_LIBRARY_PATH=/opt/riegl/rivlib/current/lib:/opt/riegl/rdblib/current/library
```

### Ports
No ports are exposed by default. Add to `devcontainer.json` if needed:

```json
"forwardPorts": [8888],  // For Jupyter
```

## Without RIEGL Libraries

If you don't have the RIEGL library files, the container will still work but only with LEAF data format support. The setup script will skip RIEGL library installation and the package will build without the proprietary drivers.

## Troubleshooting

### Container fails to build
- Check Docker is running
- Ensure you have enough disk space (>5GB for full build)
- Try rebuilding: `Dev Containers: Rebuild Container`

### RIEGL libraries not working
- Verify files are in `riegl_libs/` directory with exact names
- Check permissions: `ls -la riegl_libs/*.zip riegl_libs/*.tar.gz`
- Rebuild container to re-run setup: `Dev Containers: Rebuild Container`

### Python package not importing
```bash
# Reinstall in editable mode
micromamba run -n pylidar-tls-canopy pip install -e . -v
```

### C extensions compilation errors
- Ensure RIEGL libraries extracted correctly: `ls -la /opt/riegl/*/current`
- Check environment variables: `env | grep RIEGL`
- Review build output for specific errors

## Customization

### Add Python packages
Edit `environment.yml` and rebuild container.

### Add VS Code extensions
Add to `customizations.vscode.extensions` in `devcontainer.json`.

### Change Python version
Update `environment.yml` and rebuild.

### Mount additional volumes
Add to `mounts` array in `devcontainer.json`:

```json
"mounts": [
    "source=/path/on/host,target=/path/in/container,type=bind"
]
```

## Performance Notes

- First build takes ~10 minutes (downloads base image + dependencies)
- Subsequent builds use cached layers (~1-2 minutes)
- RIEGL library setup runs only on first container creation
- File operations on mounted volumes may be slower than native (use Docker volumes for better performance if needed)

## Container vs Local GitHub Actions

The container built here is similar but not identical to the GitHub Actions workflow container:
- **Devcontainer**: Optimized for development with VS Code integration
- **GitHub Actions**: Optimized for CI/CD with automated builds and publishing

Both use the same base configuration from `environment.yml` and RIEGL libraries.
