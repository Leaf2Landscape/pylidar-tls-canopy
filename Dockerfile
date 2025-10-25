FROM mambaorg/micromamba:1.5-jammy

USER root

# Install system dependencies and compilers
RUN apt-get update && apt-get install -y \
    build-essential \
    g++ \
    git \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Create directories for RIEGL libraries
RUN mkdir -p /opt/riegl/rivlib /opt/riegl/rdblib

# Copy decrypted RIEGL libraries from .riegl_libs directory
# The GitHub Actions workflow decrypts the .gpg files before building
COPY .riegl_libs /tmp/riegl_libs/

# Extract RIEGL libraries if they exist
RUN if [ "$(ls -A /tmp/riegl_libs 2>/dev/null)" ]; then \
        echo "Installing RIEGL libraries from build context..."; \
        # Debug: Show what's in the build context \
        echo "Contents of /tmp/riegl_libs:"; ls -la /tmp/riegl_libs/ || true; \
        # Find and extract archives \
        find /tmp/riegl_libs -name "rivlib*.tar.gz" -exec tar -xzf {} -C /opt/riegl/rivlib \; 2>/dev/null || true; \
        find /tmp/riegl_libs -name "rivlib*.zip" -exec unzip -q {} -d /opt/riegl/rivlib \; 2>/dev/null || true; \
        find /tmp/riegl_libs -name "rdblib*.tar.gz" -exec tar -xzf {} -C /opt/riegl/rdblib \; 2>/dev/null || true; \
        # Debug: Show what was extracted \
        echo "Contents of /opt/riegl/rivlib:"; ls -la /opt/riegl/rivlib/ || true; \
        echo "Contents of /opt/riegl/rdblib:"; ls -la /opt/riegl/rdblib/ || true; \
        # Create symlinks to 'current' for consistent paths \
        RIVLIB_DIR=$(find /opt/riegl/rivlib -maxdepth 1 -type d -name "rivlib-*" | head -1); \
        RDBLIB_DIR=$(find /opt/riegl/rdblib -maxdepth 1 -type d -name "rdblib-*" | head -1); \
        echo "RIVLIB_DIR=$RIVLIB_DIR"; \
        echo "RDBLIB_DIR=$RDBLIB_DIR"; \
        if [ -n "$RIVLIB_DIR" ]; then ln -sf "$RIVLIB_DIR" /opt/riegl/rivlib/current; fi; \
        if [ -n "$RDBLIB_DIR" ]; then ln -sf "$RDBLIB_DIR" /opt/riegl/rdblib/current; fi; \
        # Verify symlinks and library files exist \
        echo "Checking symlinks:"; \
        ls -la /opt/riegl/rivlib/current || echo "RiVLib symlink missing"; \
        ls -la /opt/riegl/rdblib/current || echo "RDBLib symlink missing"; \
        ls -la /opt/riegl/rdblib/current/library/ || echo "RDBLib library directory missing"; \
        rm -rf /tmp/riegl_libs; \
        echo "RIEGL libraries installed"; \
    else \
        echo "No RIEGL libraries found - extensions will not be built"; \
    fi

USER $MAMBA_USER

# Copy environment file
COPY --chown=$MAMBA_USER:$MAMBA_USER environment.yml /tmp/environment.yml

# Update environment.yml with correct paths for container and remove pip install and variables sections
RUN sed -i '/pip:/,/- -e \./d' /tmp/environment.yml && \
    sed -i '/variables:/d' /tmp/environment.yml && \
    sed -i '/RIVLIB_ROOT:/d' /tmp/environment.yml && \
    sed -i '/RDBLIB_ROOT:/d' /tmp/environment.yml && \
    sed -i '/PYLIDAR_CXX_FLAGS:/d' /tmp/environment.yml

# Create conda environment
RUN micromamba create -f /tmp/environment.yml && \
    micromamba clean --all --yes

# Copy the rest of the application
COPY --chown=$MAMBA_USER:$MAMBA_USER . /app
WORKDIR /app

# Set environment variables for building with RIEGL libraries
ENV RIVLIB_ROOT=/opt/riegl/rivlib/current
ENV RDBLIB_ROOT=/opt/riegl/rdblib/current
ENV PYLIDAR_CXX_FLAGS="-std=c++11"
ENV LD_LIBRARY_PATH=/opt/riegl/rivlib/current/lib:/opt/riegl/rdblib/current/library

# Activate environment and install the package
ARG MAMBA_DOCKERFILE_ACTIVATE=1
RUN micromamba run -n pylidar-tls-canopy pip install . -v

# Set entrypoint to use the conda environment
ENTRYPOINT ["/usr/local/bin/_entrypoint.sh"]
CMD ["/bin/bash"]
