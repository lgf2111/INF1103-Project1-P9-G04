#!/usr/bin/env bash
# Simple helper to build and run PhishReport with Docker.
#
# Usage:
#   bash run.sh build     # build the CLI Docker image
#   bash run.sh run       # run the CLI (loads your key from .env)
#   bash run.sh test      # run the tests inside the container
#   bash run.sh telegram # run the Telegram bot (loads .env)
#   bash run.sh shell     # open a shell inside the container
#   bash run.sh clean     # remove the Docker images
#
# Run from macOS/Linux Bash or Windows Git Bash/WSL. Docker Desktop/Engine
# must be installed and running. The CLI additionally needs a .env API key.

IMAGE="phishreport"
TELEGRAM_IMAGE="${IMAGE}-telegram"

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

ensure_image() {
    if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
        echo "The $IMAGE image is not built yet; building it now..."
        docker build -t "$IMAGE" "$(docker_path "$PROJECT_DIR")"
    fi
}

if [ "$command" = "build" ]; then
    echo "Building the $IMAGE image..."
    docker build -t "$IMAGE" "$(docker_path "$PROJECT_DIR")"
    echo "Done. Start the app with: bash run.sh run"

elif [ "$command" = "run" ]; then
    if [ ! -f "$PROJECT_DIR/.env" ]; then
        echo "No .env file found."
        echo "Copy .env.example to .env and add your GROQ_API_KEY before running the CLI."
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

    ensure_image
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
        "$IMAGE" python -m phishreport.cli

elif [ "$command" = "test" ]; then
    ensure_image
    echo "Running the tests inside the container..."
    docker run --rm --network none "$IMAGE" pytest

elif [ "$command" = "telegram" ]; then
    TELEGRAM_ENV="$PROJECT_DIR/.env"
    if [ ! -f "$TELEGRAM_ENV" ]; then
        echo "Copy .env.example to .env and set TELEGRAM_BOT_TOKEN (TELEGRAM_ALLOWED_CHAT_ID is optional)."
        exit 1
    fi

    if ! docker image inspect "$TELEGRAM_IMAGE" >/dev/null 2>&1; then
        docker build --target telegram -t "$TELEGRAM_IMAGE" "$(docker_path "$PROJECT_DIR")"
    fi
    mkdir -p "$DATA_DIR"
    echo "Starting the Telegram bot (Ctrl+C to stop)."
    echo "Once it says it is running, follow the steps it prints, then in Telegram:"
    echo "  /start        welcome and connection check"
    echo "  /linkgmail    watch your Gmail for phishing (needs a Google app password)"
    echo "Linked Gmail details are kept in $DATA_DIR/gmail_accounts.json (keep it private)."
    docker run --rm \
        --env-file "$(docker_path "$TELEGRAM_ENV")" \
        -v "$(docker_path "$DATA_DIR"):/data" \
        "$TELEGRAM_IMAGE"

elif [ "$command" = "shell" ]; then
    # Open an interactive shell INSIDE the container so you can look around
    # (Docker containers have no SSH; this is how you "get inside" one).
    # Loads .env if you have it, so your key is available in there too.
    ensure_image
    echo "Opening a shell inside the container (type 'exit' to leave)..."
    if [ -f "$PROJECT_DIR/.env" ]; then
        docker run --rm -it --env-file "$(docker_path "$PROJECT_DIR/.env")" "$IMAGE" /bin/bash
    else
        docker run --rm -it "$IMAGE" /bin/bash
    fi

elif [ "$command" = "clean" ]; then
    for image in "$IMAGE" "$TELEGRAM_IMAGE"; do
        if docker image inspect "$image" >/dev/null 2>&1; then
            echo "Removing the $image image..."
            docker rmi "$image"
        fi
    done

else
    echo "PhishReport Docker runner"
    echo ""
    echo "Usage: bash run.sh [command]"
    echo ""
    echo "  build   build the CLI Docker image"
    echo "  run     build if needed and run the CLI (needs .env with GROQ_API_KEY)"
    echo "  telegram build if needed and run the bot (needs Telegram settings in .env)"
    echo "  test    run the tests in the container"
    echo "  shell   build if needed and open a shell inside the container"
    echo "  clean   delete the CLI and Telegram images"
fi
