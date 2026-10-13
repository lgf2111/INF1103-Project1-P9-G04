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
DATA_DIR="$PROJECT_DIR/.phishreport-data"
command="${1:-}"

# I convert host paths explicitly for Git Bash and keep container paths literal.
export MSYS_NO_PATHCONV=1

docker_path() {
    if command -v cygpath >/dev/null 2>&1; then
        cygpath -m "$1"
    else
        printf '%s' "$1"
    fi
}

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

prepare_data_file() {
    name="$1"
    initial_content="$2"
    destination="$DATA_DIR/$name"
    legacy="$PROJECT_DIR/$name"
    # I copy existing host files once; later runs keep the newer data directory.
    if [ ! -e "$destination" ] && [ -e "$legacy" ]; then
        if [ ! -f "$legacy" ]; then
            echo "Expected a file but found a directory: $legacy"
            exit 1
        fi
        cp "$legacy" "$destination"
    fi
    ensure_data_file "$destination" "$initial_content"
}

if [ "$command" = "build" ]; then
    echo "Building the $IMAGE image..."
    docker build -t "$IMAGE" "$(docker_path "$PROJECT_DIR")"
    echo "Done. Now run:  ./docker.sh run"

elif [ "$command" = "run" ]; then
    if [ ! -f "$PROJECT_DIR/.env" ]; then
        echo "No .env file found. Make one with:  GROQ_API_KEY=your_key"
        exit 1
    fi

    # The default import folder is local runtime state, not a tracked placeholder.
    if [ -z "${PHISHREPORT_EMAIL_DIR:-}" ]; then
        mkdir -p "$PROJECT_DIR/emails"
    fi
    EMAIL_DIR="${PHISHREPORT_EMAIL_DIR:-$PROJECT_DIR/emails}"
    case "$EMAIL_DIR" in
        /*|[A-Za-z]:[\\/]*) ;;
        *) EMAIL_DIR="$PROJECT_DIR/$EMAIL_DIR" ;;
    esac
    if [ ! -d "$EMAIL_DIR" ]; then
        echo "Email folder does not exist: $EMAIL_DIR"
        exit 1
    fi
    EMAIL_DIR="$(CDPATH= cd -- "$EMAIL_DIR" && pwd -P)"

    mkdir -p "$DATA_DIR"
    prepare_data_file "reports.json" "[]"
    prepare_data_file ".phishreport_config.json" "{}"
    if [ ! -e "$DATA_DIR/logs" ] && [ -d "$PROJECT_DIR/logs" ]; then
        cp -R "$PROJECT_DIR/logs" "$DATA_DIR/logs"
    fi
    mkdir -p "$DATA_DIR/logs"

    echo "Starting the app (Ctrl+C to quit)..."
    echo "Reports, settings and logs: $DATA_DIR"
    echo "For the email folder picker, enter /emails (host folder: $EMAIL_DIR)."
    # I mount the directory so atomic report replacement can create/rename siblings.
    docker run --rm -it \
        -p 127.0.0.1:8000:8000 \
        --env-file "$(docker_path "$PROJECT_DIR/.env")" \
        -v "$(docker_path "$DATA_DIR"):/data" \
        -v "$(docker_path "$EMAIL_DIR"):/emails:ro" \
        -w /data \
        "$IMAGE" python /app/app/main.py

elif [ "$command" = "test" ]; then
    echo "Running the tests inside the container..."
    docker run --rm --network none "$IMAGE" pytest

elif [ "$command" = "shell" ]; then
    # Open an interactive shell INSIDE the container so you can look around
    # (Docker containers have no SSH; this is how you "get inside" one).
    # Loads .env if you have it, so your key is available in there too.
    echo "Opening a shell inside the container (type 'exit' to leave)..."
    if [ -f "$PROJECT_DIR/.env" ]; then
        docker run --rm -it --env-file "$(docker_path "$PROJECT_DIR/.env")" "$IMAGE" /bin/bash
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
