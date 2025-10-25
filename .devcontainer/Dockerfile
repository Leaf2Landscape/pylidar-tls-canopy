FROM docker.io/mambaorg/micromamba:1.5-jammy

USER root

# Install system dependencies and compilers
RUN apt-get update && apt-get install -y \
    build-essential \
    g++ \
    git \
    unzip \
    curl \
    vim \
    sudo \
    && rm -rf /var/lib/apt/lists/*

# Configure sudo for mambauser
RUN echo "mambauser ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers.d/mambauser && \
    chmod 0440 /etc/sudoers.d/mambauser

# Create directories for RIEGL libraries
RUN mkdir -p /opt/riegl/rivlib /opt/riegl/rdblib

USER $MAMBA_USER

# Copy environment file
COPY environment.yml /tmp/environment.yml

# Update environment.yml with correct paths for container and remove pip install and variables sections
RUN sed '/pip:/,/- -e \./d' /tmp/environment.yml | \
    sed '/variables:/d' | \
    sed '/RIVLIB_ROOT:/d' | \
    sed '/RDBLIB_ROOT:/d' | \
    sed '/PYLIDAR_CXX_FLAGS:/d' > /tmp/environment-clean.yml

# Create conda environment
RUN micromamba create -f /tmp/environment-clean.yml && \
    micromamba clean --all --yes

USER root
# Fix permissions for conda environment so mambauser can install packages
RUN chown -R $MAMBA_USER:$MAMBA_USER /opt/conda/envs/pylidar-tls-canopy
USER $MAMBA_USER

# Set working directory
WORKDIR /workspace

# Note: RIEGL libraries will be mounted and extracted at runtime via postCreateCommand
# This keeps the image smaller and allows for easier updates

USER root

# Copy RIEGL libraries if provided during build (GitHub Actions)
# For local builds, the workflow ensures .riegl_libs directory exists (may be empty)
COPY .riegl_libs /tmp/riegl_libs/

# Install RIEGL libraries from build-time copy or prepare for runtime mounting
RUN if [ "$(ls -A /tmp/riegl_libs 2>/dev/null)" ]; then \
        echo "Installing RIEGL libraries from build context..."; \
        # Find and extract archives
        find /tmp/riegl_libs -name "*.tar.gz" -exec tar -xzf {} -C /opt/riegl/rivlib \; 2>/dev/null || true; \
        find /tmp/riegl_libs -name "*.zip" -exec unzip -q {} -d /opt/riegl/rivlib \; 2>/dev/null || true; \
        # Create symlinks to 'current' for consistent paths
        RIVLIB_DIR=$(find /opt/riegl/rivlib -maxdepth 1 -type d -name "rivlib-*" | head -1); \
        RDBLIB_DIR=$(find /opt/riegl/rdblib -maxdepth 1 -type d -name "rdblib-*" | head -1); \
        if [ -n "$RIVLIB_DIR" ]; then ln -sf "$RIVLIB_DIR" /opt/riegl/rivlib/current; fi; \
        if [ -n "$RDBLIB_DIR" ]; then ln -sf "$RDBLIB_DIR" /opt/riegl/rdblib/current; fi; \
        rm -rf /tmp/riegl_libs; \
        echo "RIEGL libraries installed at build time"; \
    else \
        echo "No RIEGL libraries in build context - will use runtime mounting"; \
    fi

# Create a script to setup RIEGL libraries at runtime (for local development)
RUN echo '#!/bin/bash\n\
# Skip if libraries already installed at build time\n\
if [ -L /opt/riegl/rivlib/current ] && [ -L /opt/riegl/rdblib/current ]; then\n\
    echo "RIEGL libraries already installed (build-time)"\n\
    exit 0\n\
fi\n\
\n\
if [ ! -f /opt/riegl/.setup_complete ]; then\n\
    echo "Setting up RIEGL libraries from mounted volume..."\n\
    \n\
    # Look for RiVLib archives\n\
    RIVLIB_ARCHIVE=$(find /workspace/riegl_libs -name "rivlib*.tar.gz" -o -name "rivlib*.zip" 2>/dev/null | head -1)\n\
    if [ -n "$RIVLIB_ARCHIVE" ]; then\n\
        echo "Extracting RiVLib from $RIVLIB_ARCHIVE"\n\
        if [[ "$RIVLIB_ARCHIVE" == *.tar.gz ]]; then\n\
            tar -xzf "$RIVLIB_ARCHIVE" -C /opt/riegl/rivlib\n\
        else\n\
            unzip -q "$RIVLIB_ARCHIVE" -d /opt/riegl/rivlib\n\
        fi\n\
    fi\n\
    \n\
    # Look for RDBLib archives\n\
    RDBLIB_ARCHIVE=$(find /workspace/riegl_libs -name "rdblib*.tar.gz" 2>/dev/null | head -1)\n\
    if [ -n "$RDBLIB_ARCHIVE" ]; then\n\
        echo "Extracting RDBLib from $RDBLIB_ARCHIVE"\n\
        tar -xzf "$RDBLIB_ARCHIVE" -C /opt/riegl/rdblib\n\
    fi\n\
    \n\
    # Create symlinks\n\
    RIVLIB_DIR=$(find /opt/riegl/rivlib -maxdepth 1 -type d -name "rivlib-*" | head -1)\n\
    RDBLIB_DIR=$(find /opt/riegl/rdblib -maxdepth 1 -type d -name "rdblib-*" | head -1)\n\
    if [ -n "$RIVLIB_DIR" ]; then\n\
        ln -sf "$RIVLIB_DIR" /opt/riegl/rivlib/current\n\
        echo "RiVLib installed: $RIVLIB_DIR"\n\
    fi\n\
    if [ -n "$RDBLIB_DIR" ]; then\n\
        ln -sf "$RDBLIB_DIR" /opt/riegl/rdblib/current\n\
        echo "RDBLib installed: $RDBLIB_DIR"\n\
    fi\n\
    \n\
    touch /opt/riegl/.setup_complete\n\
    echo "RIEGL libraries setup complete"\n\
else\n\
    echo "RIEGL libraries already set up"\n\
fi\n' > /usr/local/bin/setup-riegl.sh && \
    chmod +x /usr/local/bin/setup-riegl.sh

USER $MAMBA_USER

# Set environment variables for building with RIEGL libraries
ENV RIVLIB_ROOT=/opt/riegl/rivlib/current
ENV RDBLIB_ROOT=/opt/riegl/rdblib/current
ENV PYLIDAR_CXX_FLAGS="-std=c++11"
ENV LD_LIBRARY_PATH=/opt/riegl/rivlib/current/lib:/opt/riegl/rdblib/current/library

# Set entrypoint to use the conda environment and setup RIEGL
ENTRYPOINT ["/usr/local/bin/_entrypoint.sh"]

# Activate conda environment by default and set up aliases
RUN echo "micromamba activate pylidar-tls-canopy" >> /home/$MAMBA_USER/.bashrc && \
    echo 'alias python="/opt/conda/envs/pylidar-tls-canopy/bin/python"' >> /home/$MAMBA_USER/.bashrc && \
    echo 'alias pip="/opt/conda/envs/pylidar-tls-canopy/bin/pip"' >> /home/$MAMBA_USER/.bashrc

CMD ["/bin/bash"]
