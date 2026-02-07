#!/bin/bash
# Combined processing script for batch_pavd_profiles.py, batch_voxelization.py,
# batch_grid_visualization.py, and batch_hemispherical_images.py
# Usage: ./run_processing.sh [profiles|voxels|grid|hemi|all]

set -o pipefail

PATH=/home/tim/.conda/envs/pylidar-tls-canopy/bin:$PATH
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# RIEGL library environment variables
export RDBLIB_ROOT=/home/tim/Code/pylidar-tls-canopy-1/riegl_libs/rdblib-2.4.1-x86_64-linux
export RIVLIB_ROOT=/home/tim/Code/pylidar-tls-canopy-1/riegl_libs/rivlib-2_6_0-x86_64-linux-gcc11
export PYLIDAR_CXX_FLAGS="-std=c++11"
export LD_LIBRARY_PATH="${RDBLIB_ROOT}/library:${RIVLIB_ROOT}/lib:${LD_LIBRARY_PATH}"

# Track processing results
FAILED_TASKS=()
SUCCESSFUL_TASKS=()
SKIPPED_TASKS=()

# Resource monitoring settings
MONITOR_INTERVAL=10  # seconds between samples
MONITOR_PID=""
RESOURCE_LOG=""
START_TIME=""

# Output directory (can be overridden with --output-dir)
OUTPUT_DIR=""

# Parallel processing settings
PARALLEL_MODE=false
MAX_PARALLEL=4

# Skip existing output
SKIP_EXISTING=false

# Linear-only PAVD profiles
LINEAR_ONLY=false

# Projects file (default: projects.txt in script directory)
PROJECTS_FILE=""

# ==========================================
# Resource monitoring functions
# ==========================================

start_resource_monitor() {
    RESOURCE_LOG="$OUTPUT_DIR/resource_usage_$(date +%Y%m%d_%H%M%S).log"
    START_TIME=$(date +%s)

    echo "Starting resource monitor (logging every ${MONITOR_INTERVAL}s to $RESOURCE_LOG)"

    # Write header to log
    {
        echo "# Resource monitoring started: $(date)"
        echo "# User: $USER"
        echo "# Interval: ${MONITOR_INTERVAL}s"
        echo "# Format: timestamp | User CPU | User Memory (GB + %) | Top process | System load"
        echo "#"
    } > "$RESOURCE_LOG"

    # Start background monitoring loop
    (
        while true; do
            # Get user's total CPU and memory usage
            USER_STATS=$(ps -u "$USER" -o pid=,pcpu=,pmem=,rss=,comm= --no-headers 2>/dev/null | \
                awk '{cpu+=$2; mem+=$3; rss+=$4} END {printf "%.1f%% %.1f%% %.2f", cpu, mem, rss/1024/1024}')
            USER_CPU=$(echo "$USER_STATS" | awk '{print $1}')
            USER_MEM_PCT=$(echo "$USER_STATS" | awk '{print $2}')
            USER_MEM_GB=$(echo "$USER_STATS" | awk '{print $3}')

            # Get top process by memory for this user
            TOP_PROC=$(ps -u "$USER" -o pcpu=,pmem=,rss=,comm= --no-headers 2>/dev/null | \
                sort -k3 -rn | head -1 | awk '{printf "%.1f%% %.2fGB %s", $2, $3/1024/1024, $4}')

            # Get system load average
            LOAD_AVG=$(uptime | awk -F'load average:' '{print $2}' | xargs)

            # Write to log with timestamp
            echo "$(date '+%Y-%m-%d %H:%M:%S') | User CPU: ${USER_CPU} | User Mem: ${USER_MEM_GB}GB (${USER_MEM_PCT}) | Top: ${TOP_PROC} | Load: ${LOAD_AVG}" >> "$RESOURCE_LOG"

            sleep "$MONITOR_INTERVAL"
        done
    ) &
    MONITOR_PID=$!
}

stop_resource_monitor() {
    if [ -n "$MONITOR_PID" ] && kill -0 "$MONITOR_PID" 2>/dev/null; then
        kill "$MONITOR_PID" 2>/dev/null
        wait "$MONITOR_PID" 2>/dev/null

        # Calculate elapsed time
        if [ -n "$START_TIME" ]; then
            local END_TIME=$(date +%s)
            local ELAPSED=$((END_TIME - START_TIME))
            local HOURS=$((ELAPSED / 3600))
            local MINUTES=$(((ELAPSED % 3600) / 60))
            local SECONDS=$((ELAPSED % 60))

            echo ""
            echo "# Monitoring stopped: $(date)" >> "$RESOURCE_LOG"
            echo "# Total elapsed time: ${HOURS}h ${MINUTES}m ${SECONDS}s" >> "$RESOURCE_LOG"

            echo "Resource monitoring stopped (elapsed: ${HOURS}h ${MINUTES}m ${SECONDS}s)"
            echo "Resource log saved to: $RESOURCE_LOG"
        fi
    fi
}

# Cleanup and summary on exit
cleanup() {
    local exit_code=$?

    # Stop resource monitoring first
    stop_resource_monitor

    echo ""
    echo "=========================================="
    echo "Processing Summary"
    echo "=========================================="
    echo "Successful: ${#SUCCESSFUL_TASKS[@]}"
    echo "Failed:     ${#FAILED_TASKS[@]}"
    echo "Skipped:    ${#SKIPPED_TASKS[@]}"

    if [ ${#FAILED_TASKS[@]} -gt 0 ]; then
        echo ""
        echo "Failed tasks:"
        for task in "${FAILED_TASKS[@]}"; do
            echo "  - $task"
        done
    fi

    if [ ${#SKIPPED_TASKS[@]} -gt 0 ]; then
        echo ""
        echo "Skipped tasks:"
        for task in "${SKIPPED_TASKS[@]}"; do
            echo "  - $task"
        done
    fi

    if [ -n "$RESOURCE_LOG" ] && [ -f "$RESOURCE_LOG" ]; then
        echo ""
        echo "Resource log: $RESOURCE_LOG"
    fi

    exit $exit_code
}
trap cleanup EXIT

# ==========================================
# Processing functions
# ==========================================

extract_transforms() {
    local PROJECT_NAME=$1
    local RISCAN_DIR=$2
    local TASK_NAME="extract_transforms:$PROJECT_NAME"

    echo ""
    echo "------------------------------------------"
    echo "Extracting transforms for $PROJECT_NAME..."
    echo "------------------------------------------"

    if [ ! -d "$RISCAN_DIR" ]; then
        echo "WARNING: Skipping $TASK_NAME: RiSCAN directory not found at $RISCAN_DIR"
        SKIPPED_TASKS+=("$TASK_NAME")
        return 0
    fi

    local RSP_FILE="$RISCAN_DIR/project.rsp"
    if [ ! -f "$RSP_FILE" ]; then
        echo "WARNING: Skipping $TASK_NAME: project.rsp not found at $RSP_FILE"
        SKIPPED_TASKS+=("$TASK_NAME")
        return 0
    fi

    if python "$SCRIPT_DIR/extract_transforms.py" "$RSP_FILE"; then
        echo "SUCCESS: $TASK_NAME completed"
        SUCCESSFUL_TASKS+=("$TASK_NAME")
        return 0
    else
        local exit_code=$?
        echo "ERROR: $TASK_NAME failed with exit code $exit_code"
        FAILED_TASKS+=("$TASK_NAME (exit code: $exit_code)")
        return $exit_code
    fi
}

run_profiles() {
    local PROJECT_NAME=$1
    local RISCAN_DIR=$2
    local TASK_NAME="profiles:$PROJECT_NAME"
    local PROFILES_OUTPUT="$OUTPUT_DIR/pavd_output/$PROJECT_NAME"

    echo ""
    echo "------------------------------------------"
    echo "Running PAVD profiles for $PROJECT_NAME..."
    echo "Output: $PROFILES_OUTPUT"
    echo "------------------------------------------"

    if [ ! -d "$RISCAN_DIR" ]; then
        echo "WARNING: Skipping $TASK_NAME: RiSCAN directory not found at $RISCAN_DIR"
        SKIPPED_TASKS+=("$TASK_NAME")
        return 0
    fi

    # Build optional flags
    local SKIP_FLAG=""
    if [ "$SKIP_EXISTING" = true ]; then
        SKIP_FLAG="--skip-existing"
    fi
    local LINEAR_FLAG=""
    if [ "$LINEAR_ONLY" = true ]; then
        LINEAR_FLAG="--linear-only"
    fi

    if python "$SCRIPT_DIR/batch_pavd_profiles.py" \
        --hres 0.5 \
        --zres 5 \
        --ares 90 \
        --min-zenith 35 \
        --max-zenith 70 \
        --min-height 0 \
        --max-height 100 \
        --reflectance-threshold -20 \
        --method WEIGHTED \
        --output "$PROFILES_OUTPUT" \
        $SKIP_FLAG \
        $LINEAR_FLAG \
        "$RISCAN_DIR"; then
        echo "SUCCESS: $TASK_NAME completed"
        SUCCESSFUL_TASKS+=("$TASK_NAME")
        return 0
    else
        local exit_code=$?
        echo "ERROR: $TASK_NAME failed with exit code $exit_code"
        FAILED_TASKS+=("$TASK_NAME (exit code: $exit_code)")
        return $exit_code
    fi
}

run_voxels() {
    local PROJECT_NAME=$1
    local RISCAN_DIR=$2
    local TASK_NAME="voxels:$PROJECT_NAME"
    local VOXELS_OUTPUT="$OUTPUT_DIR/voxel_output/$PROJECT_NAME"

    echo ""
    echo "------------------------------------------"
    echo "Running voxelization for $PROJECT_NAME..."
    echo "Output: $VOXELS_OUTPUT"
    echo "------------------------------------------"

    if [ ! -d "$RISCAN_DIR" ]; then
        echo "WARNING: Skipping $TASK_NAME: RiSCAN directory not found at $RISCAN_DIR"
        SKIPPED_TASKS+=("$TASK_NAME")
        return 0
    fi

    if python "$SCRIPT_DIR/batch_voxelization.py" \
        --voxelsize 0.5 \
        --merged \
        --output "$VOXELS_OUTPUT" \
        "$RISCAN_DIR"; then
        echo "SUCCESS: $TASK_NAME completed"
        SUCCESSFUL_TASKS+=("$TASK_NAME")
        return 0
    else
        local exit_code=$?
        echo "ERROR: $TASK_NAME failed with exit code $exit_code"
        FAILED_TASKS+=("$TASK_NAME (exit code: $exit_code)")
        return $exit_code
    fi
}

run_grid_viz() {
    local PROJECT_NAME=$1
    local RISCAN_DIR=$2
    local DAT_DIR=$3
    local TASK_NAME="grid_viz:$PROJECT_NAME"
    local GRID_OUTPUT="$OUTPUT_DIR/grid_output/$PROJECT_NAME"

    echo ""
    echo "------------------------------------------"
    echo "Running grid visualization for $PROJECT_NAME..."
    echo "Output: $GRID_OUTPUT"
    echo "------------------------------------------"

    if [ ! -d "$RISCAN_DIR" ]; then
        echo "WARNING: Skipping $TASK_NAME: RiSCAN directory not found at $RISCAN_DIR"
        SKIPPED_TASKS+=("$TASK_NAME")
        return 0
    fi

    # Build skip-existing flag
    local SKIP_FLAG=""
    if [ "$SKIP_EXISTING" = true ]; then
        SKIP_FLAG="--skip-existing"
    fi

    if python "$SCRIPT_DIR/batch_grid_visualization.py" \
        "$RISCAN_DIR" \
        --dat-dir "$DAT_DIR" \
        --output "$GRID_OUTPUT" \
        --grid-type distance \
        --dpi 300 \
        $SKIP_FLAG; then
        echo "SUCCESS: $TASK_NAME completed"
        SUCCESSFUL_TASKS+=("$TASK_NAME")
        return 0
    else
        local exit_code=$?
        echo "ERROR: $TASK_NAME failed with exit code $exit_code"
        FAILED_TASKS+=("$TASK_NAME (exit code: $exit_code)")
        return $exit_code
    fi
}

run_hemispherical() {
    local PROJECT_NAME=$1
    local RISCAN_DIR=$2
    local DAT_DIR=$3
    local TASK_NAME="hemispherical:$PROJECT_NAME"
    local HEMI_OUTPUT="$OUTPUT_DIR/hemispherical_output/$PROJECT_NAME"

    echo ""
    echo "------------------------------------------"
    echo "Running hemispherical images for $PROJECT_NAME..."
    echo "Output: $HEMI_OUTPUT"
    echo "------------------------------------------"

    if [ ! -d "$RISCAN_DIR" ]; then
        echo "WARNING: Skipping $TASK_NAME: RiSCAN directory not found at $RISCAN_DIR"
        SKIPPED_TASKS+=("$TASK_NAME")
        return 0
    fi

    # Build skip-existing flag
    local SKIP_FLAG=""
    if [ "$SKIP_EXISTING" = true ]; then
        SKIP_FLAG="--skip-existing"
    fi

    if python "$SCRIPT_DIR/batch_hemispherical_images.py" \
        "$RISCAN_DIR" \
        --dat-dir "$DAT_DIR" \
        --output "$HEMI_OUTPUT" \
        --resolution 0.5 \
        --attribute reflectance \
        --size 1024 \
        --view upper \
        --projection equidistant \
        --colormap gray \
        --reflectance-threshold -20 \
        $SKIP_FLAG; then
        echo "SUCCESS: $TASK_NAME completed"
        SUCCESSFUL_TASKS+=("$TASK_NAME")
        return 0
    else
        local exit_code=$?
        echo "ERROR: $TASK_NAME failed with exit code $exit_code"
        FAILED_TASKS+=("$TASK_NAME (exit code: $exit_code)")
        return $exit_code
    fi
}

# ==========================================
# Project loading
# ==========================================

load_projects() {
    local projects_file="$1"
    PROJECTS=()

    if [ ! -f "$projects_file" ]; then
        echo "ERROR: Projects file not found: $projects_file"
        exit 1
    fi

    while IFS= read -r line || [ -n "$line" ]; do
        # Skip empty lines and comments
        [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
        # Trim whitespace
        line=$(echo "$line" | xargs)
        [ -n "$line" ] && PROJECTS+=("$line")
    done < "$projects_file"

    if [ ${#PROJECTS[@]} -eq 0 ]; then
        echo "ERROR: No projects found in $projects_file"
        exit 1
    fi

    echo "Loaded ${#PROJECTS[@]} projects from $projects_file"
}

# ==========================================
# Main execution
# ==========================================

process_single_project() {
    local MODE=$1
    local PROJECT_NAME=$2
    local RISCAN_DIR=$3
    local DAT_DIR=$4
    local LOG_FILE="$OUTPUT_DIR/logs/${PROJECT_NAME}_$(date +%Y%m%d_%H%M%S).log"

    # Create logs directory
    mkdir -p "$OUTPUT_DIR/logs"

    # Redirect output to log file for parallel mode
    exec > >(tee -a "$LOG_FILE") 2>&1

    echo ""
    echo "=========================================="
    echo "Project: $PROJECT_NAME"
    echo "Log: $LOG_FILE"
    echo "=========================================="

    # Always extract transforms first (unless running extract-only mode)
    if [ "$MODE" != "extract" ]; then
        extract_transforms "$PROJECT_NAME" "$RISCAN_DIR"
    fi

    case "$MODE" in
        extract)
            extract_transforms "$PROJECT_NAME" "$RISCAN_DIR"
            ;;
        profiles)
            run_profiles "$PROJECT_NAME" "$RISCAN_DIR"
            ;;
        voxels)
            run_voxels "$PROJECT_NAME" "$RISCAN_DIR"
            ;;
        grid)
            run_grid_viz "$PROJECT_NAME" "$RISCAN_DIR" "$DAT_DIR"
            ;;
        hemi)
            run_hemispherical "$PROJECT_NAME" "$RISCAN_DIR" "$DAT_DIR"
            ;;
        novoxels)
            run_profiles "$PROJECT_NAME" "$RISCAN_DIR"
            run_grid_viz "$PROJECT_NAME" "$RISCAN_DIR" "$DAT_DIR"
            run_hemispherical "$PROJECT_NAME" "$RISCAN_DIR" "$DAT_DIR"
            ;;
        all)
            run_profiles "$PROJECT_NAME" "$RISCAN_DIR"
            run_voxels "$PROJECT_NAME" "$RISCAN_DIR"
            run_grid_viz "$PROJECT_NAME" "$RISCAN_DIR" "$DAT_DIR"
            run_hemispherical "$PROJECT_NAME" "$RISCAN_DIR" "$DAT_DIR"
            ;;
    esac

    echo ""
    echo "=========================================="
    echo "Finished: $PROJECT_NAME"
    echo "=========================================="
}

process_all_projects() {
    local MODE=$1

    if [ "$PARALLEL_MODE" = true ]; then
        echo "Running in PARALLEL mode (max $MAX_PARALLEL concurrent projects)"
        echo ""

        local PIDS=()
        local PROJECT_NAMES=()
        local running=0

        for project_entry in "${PROJECTS[@]}"; do
            [[ "$project_entry" =~ ^# ]] && continue

            IFS='|' read -r PROJECT_NAME RISCAN_DIR DAT_DIR <<< "$project_entry"

            # Wait if we've reached max parallel jobs
            while [ $running -ge $MAX_PARALLEL ]; do
                # Wait for any job to finish
                for i in "${!PIDS[@]}"; do
                    if ! kill -0 "${PIDS[$i]}" 2>/dev/null; then
                        wait "${PIDS[$i]}"
                        local exit_code=$?
                        if [ $exit_code -eq 0 ]; then
                            echo "[DONE] ${PROJECT_NAMES[$i]} completed successfully"
                            SUCCESSFUL_TASKS+=("${PROJECT_NAMES[$i]}")
                        else
                            echo "[FAIL] ${PROJECT_NAMES[$i]} failed with exit code $exit_code"
                            FAILED_TASKS+=("${PROJECT_NAMES[$i]} (exit code: $exit_code)")
                        fi
                        unset 'PIDS[$i]'
                        unset 'PROJECT_NAMES[$i]'
                        ((running--))
                    fi
                done
                # Compact arrays
                PIDS=("${PIDS[@]}")
                PROJECT_NAMES=("${PROJECT_NAMES[@]}")
                sleep 1
            done

            echo "[START] Launching $PROJECT_NAME in background..."
            process_single_project "$MODE" "$PROJECT_NAME" "$RISCAN_DIR" "$DAT_DIR" &
            PIDS+=($!)
            PROJECT_NAMES+=("$PROJECT_NAME")
            ((running++))
        done

        # Wait for remaining jobs
        echo ""
        echo "Waiting for remaining jobs to complete..."
        for i in "${!PIDS[@]}"; do
            wait "${PIDS[$i]}"
            local exit_code=$?
            if [ $exit_code -eq 0 ]; then
                echo "[DONE] ${PROJECT_NAMES[$i]} completed successfully"
                SUCCESSFUL_TASKS+=("${PROJECT_NAMES[$i]}")
            else
                echo "[FAIL] ${PROJECT_NAMES[$i]} failed with exit code $exit_code"
                FAILED_TASKS+=("${PROJECT_NAMES[$i]} (exit code: $exit_code)")
            fi
        done

    else
        # Sequential mode (original behavior)
        for project_entry in "${PROJECTS[@]}"; do
            [[ "$project_entry" =~ ^# ]] && continue

            IFS='|' read -r PROJECT_NAME RISCAN_DIR DAT_DIR <<< "$project_entry"

            echo ""
            echo "=========================================="
            echo "Project: $PROJECT_NAME"
            echo "=========================================="

            # Always extract transforms first (unless running extract-only mode)
            if [ "$MODE" != "extract" ]; then
                extract_transforms "$PROJECT_NAME" "$RISCAN_DIR"
            fi

            case "$MODE" in
                extract)
                    extract_transforms "$PROJECT_NAME" "$RISCAN_DIR"
                    ;;
                profiles)
                    run_profiles "$PROJECT_NAME" "$RISCAN_DIR"
                    ;;
                voxels)
                    run_voxels "$PROJECT_NAME" "$RISCAN_DIR"
                    ;;
                grid)
                    run_grid_viz "$PROJECT_NAME" "$RISCAN_DIR" "$DAT_DIR"
                    ;;
                hemi)
                    run_hemispherical "$PROJECT_NAME" "$RISCAN_DIR" "$DAT_DIR"
                    ;;
                novoxels)
                    run_profiles "$PROJECT_NAME" "$RISCAN_DIR"
                    run_grid_viz "$PROJECT_NAME" "$RISCAN_DIR" "$DAT_DIR"
                    run_hemispherical "$PROJECT_NAME" "$RISCAN_DIR" "$DAT_DIR"
                    ;;
                all)
                    run_profiles "$PROJECT_NAME" "$RISCAN_DIR"
                    run_voxels "$PROJECT_NAME" "$RISCAN_DIR"
                    run_grid_viz "$PROJECT_NAME" "$RISCAN_DIR" "$DAT_DIR"
                    run_hemispherical "$PROJECT_NAME" "$RISCAN_DIR" "$DAT_DIR"
                    ;;
            esac
        done
    fi
}

# Show usage
usage() {
    echo "Usage: $0 [MODE] [OPTIONS]"
    echo ""
    echo "Modes:"
    echo "  extract   - Extract transform matrices from project.rsp only"
    echo "  profiles  - Run batch_pavd_profiles.py for all projects"
    echo "  voxels    - Run batch_voxelization.py for all projects"
    echo "  grid      - Run batch_grid_visualization.py for all projects"
    echo "  hemi      - Run batch_hemispherical_images.py for all projects"
    echo "  novoxels  - Run profiles, grid, and hemi (skip voxelization)"
    echo "  all       - Run all processing steps for all projects"
    echo ""
    echo "Options:"
    echo "  --projects-file FILE  Path to projects file (default: scripts/projects.txt)"
    echo "  --output-dir DIR      Set output directory for all results (default: current directory)"
    echo "  --parallel            Run projects in parallel instead of sequentially"
    echo "  --max-parallel N      Maximum number of parallel projects (default: 4)"
    echo "  --skip-existing       Skip processing if output directory already has files"
    echo "  --linear-only         Only compute linear PAVD profiles (skip hinge and weighted)"
    echo "  --no-monitor          Disable resource monitoring"
    echo ""
    echo "Output structure:"
    echo "  <output-dir>/"
    echo "    pavd_output/<project>/         - PAVD profile results"
    echo "    voxel_output/<project>/        - Voxelization results"
    echo "    grid_output/<project>/         - Grid visualization results"
    echo "    hemispherical_output/<project>/ - Hemispherical images"
    echo "    logs/<project>_*.log           - Per-project logs (parallel mode)"
    echo "    resource_usage_*.log           - Resource monitoring logs"
    echo ""
    echo "Projects file format (one project per line):"
    echo "  NAME|RISCAN_DIR|DAT_DIR"
    echo "  # Lines starting with # are comments"
    echo ""
    echo "Notes:"
    echo "  - Transform extraction runs automatically before processing modes"
    echo "  - If no mode is specified, 'all' is used by default"
}

# Parse command line arguments
MODE=""
ENABLE_MONITOR=true

while [ $# -gt 0 ]; do
    case "$1" in
        --projects-file)
            if [ -z "$2" ] || [[ "$2" == --* ]]; then
                echo "ERROR: --projects-file requires a file path"
                exit 1
            fi
            PROJECTS_FILE="$2"
            shift 2
            ;;
        --output-dir)
            if [ -z "$2" ] || [[ "$2" == --* ]]; then
                echo "ERROR: --output-dir requires a directory path"
                exit 1
            fi
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --no-monitor)
            ENABLE_MONITOR=false
            shift
            ;;
        --parallel)
            PARALLEL_MODE=true
            shift
            ;;
        --max-parallel)
            if [ -z "$2" ] || [[ "$2" == --* ]]; then
                echo "ERROR: --max-parallel requires a number"
                exit 1
            fi
            MAX_PARALLEL="$2"
            PARALLEL_MODE=true
            shift 2
            ;;
        --skip-existing)
            SKIP_EXISTING=true
            shift
            ;;
        --linear-only)
            LINEAR_ONLY=true
            shift
            ;;
        -h|--help|help)
            usage
            exit 0
            ;;
        extract|profiles|voxels|grid|hemi|novoxels|all)
            MODE="$1"
            shift
            ;;
        *)
            echo "ERROR: Unknown argument '$1'"
            echo ""
            usage
            exit 1
            ;;
    esac
done

# Default mode if not specified
MODE="${MODE:-all}"

# Default output directory to current working directory
OUTPUT_DIR="${OUTPUT_DIR:-$(pwd)}"

# Default projects file to projects.txt in script directory
PROJECTS_FILE="${PROJECTS_FILE:-$SCRIPT_DIR/projects.txt}"

# Create output directory if it doesn't exist
mkdir -p "$OUTPUT_DIR"

case "$MODE" in
    extract|profiles|voxels|grid|hemi|novoxels|all)
        echo "=========================================="
        echo "Running in '$MODE' mode"
        echo "Projects file: $PROJECTS_FILE"
        echo "Output directory: $OUTPUT_DIR"
        echo "=========================================="

        # Load projects from file
        load_projects "$PROJECTS_FILE"

        # Start resource monitoring (unless disabled)
        if [ "$ENABLE_MONITOR" = true ]; then
            start_resource_monitor
        fi

        process_all_projects "$MODE"
        ;;
esac

# Exit with error if any tasks failed
if [ ${#FAILED_TASKS[@]} -gt 0 ]; then
    exit 1
fi
