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

# Copy and extract RIEGL libraries
COPY riegl_libs/rivlib-2_6_0-x86_64-linux-gcc11.zip /tmp/
COPY riegl_libs/rdblib-2.4.1-x86_64-linux.tar.gz /tmp/

RUN unzip /tmp/rivlib-2_6_0-x86_64-linux-gcc11.zip -d /opt/riegl/rivlib && \
    tar -xzf /tmp/rdblib-2.4.1-x86_64-linux.tar.gz -C /opt/riegl/rdblib && \
    rm /tmp/rivlib-2_6_0-x86_64-linux-gcc11.zip /tmp/rdblib-2.4.1-x86_64-linux.tar.gz

# Find the actual extracted directory names and set up symlinks for consistent paths
RUN RIVLIB_DIR=$(find /opt/riegl/rivlib -maxdepth 1 -type d -name "rivlib-*" | head -1) && \
    RDBLIB_DIR=$(find /opt/riegl/rdblib -maxdepth 1 -type d -name "rdblib-*" | head -1) && \
    ln -s "$RIVLIB_DIR" /opt/riegl/rivlib/current && \
    ln -s "$RDBLIB_DIR" /opt/riegl/rdblib/current

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
