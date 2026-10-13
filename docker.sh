#!/usr/bin/env bash
# Simple helper so the team can run the app in Docker without remembering flags.
#
# Usage:
#   ./docker.sh build     # build the Docker image
#   ./docker.sh run       # run the app (loads your key from .env)
#   ./docker.sh test      # run the tests inside the container
#   ./docker.sh shell     # open a shell inside the container (to look around)
#   ./docker.sh clean     # remove the image
#
# First time only on macOS/Linux: chmod +x docker.sh
# On Windows, run this script from Git Bash or WSL: ./docker.sh run
# You need Docker Desktop open, and a .env file with your GROQ_API_KEY.

IMAGE="phishreport"

# stop and show the error if any command fails
set -e

# Resolve all paths from this script's directory, so the helper can be run
# from any working directory on macOS, Linux, Git Bash, or WSL.
PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
command="${1:-}"


ensure_data_file() {
    path="$1"
    initial_content="$2"
    if [ -e "$path" ] && [ ! -f "$path" ]; then
        echo "Expected a file but found a directory: $path"
        exit 1
    fi
    if [ ! -e "$path" ]; then
        printf '%s' "$initial_content" > "$path"
    fi
}

if [ "$command" = "build" ]; then
    echo "Building the $IMAGE image..."
    docker build -t "$IMAGE" "$PROJECT_DIR"
    echo "Done. Now run:  ./docker.sh run"

elif [ "$command" = "run" ]; then
    if [ ! -f "$PROJECT_DIR/.env" ]; then
        echo "No .env file found. Make one with:  GROQ_API_KEY=your_key"
        exit 1
    fi

    # These host paths remain after the disposable container exits.
    ensure_data_file "$PROJECT_DIR/reports.json" "[]"
    ensure_data_file "$PROJECT_DIR/.phishreport_config.json" "{}"
    mkdir -p "$PROJECT_DIR/logs"

    echo "Starting the app (Ctrl+C to quit)..."
    # The mounts preserve JSON reports, the saved .eml folder and logs. Binding
    # the port to localhost keeps the browser upload page off the local network.
    docker run --rm -it \
        -p 127.0.0.1:8000:8000 \
        --env-file "$PROJECT_DIR/.env" \
        -v "$PROJECT_DIR/reports.json:/app/reports.json" \
        -v "$PROJECT_DIR/.phishreport_config.json:/app/.phishreport_config.json" \
        -v "$PROJECT_DIR/logs:/app/logs" \
        "$IMAGE"

elif [ "$command" = "test" ]; then
    echo "Running the tests inside the container..."
    docker run --rm "$IMAGE" pytest

elif [ "$command" = "shell" ]; then
    # Open an interactive shell INSIDE the container so you can look around
    # (Docker containers have no SSH; this is how you "get inside" one).
    # Loads .env if you have it, so your key is available in there too.
    echo "Opening a shell inside the container (type 'exit' to leave)..."
    if [ -f "$PROJECT_DIR/.env" ]; then
        docker run --rm -it --env-file "$PROJECT_DIR/.env" "$IMAGE" /bin/bash
    else
        docker run --rm -it "$IMAGE" /bin/bash
    fi

elif [ "$command" = "clean" ]; then
    echo "Removing the $IMAGE image..."
    docker rmi "$IMAGE"

else
    echo "PhishReport Docker helper"
    echo ""
    echo "Usage: ./docker.sh [command]"
    echo ""
    echo "  build   build the Docker image"
    echo "  run     run the app (needs .env with GROQ_API_KEY)"
    echo "  test    run the tests in the container"
    echo "  shell   open a shell inside the container"
    echo "  clean   delete the image"
fi
