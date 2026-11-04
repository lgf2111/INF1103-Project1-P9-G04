#!/usr/bin/env bash
# Simple helper to build and run PhishReport with Docker.
#
# Usage:
#   bash run.sh build     # build the CLI Docker image
#   bash run.sh run       # run the CLI (loads your key from .env)
#   bash run.sh test      # run the tests inside the container
#   bash run.sh gui       # run the GUI in a host X11 window
#   bash run.sh gui-web   # run the GUI in a browser using noVNC
#   bash run.sh shell     # open a shell inside the container
#   bash run.sh clean     # remove the Docker images
#
# Run from macOS/Linux Bash or Windows Git Bash/WSL. Docker Desktop/Engine
# must be installed and running. The CLI additionally needs a .env API key.

IMAGE="phishreport"
GUI_IMAGE="${IMAGE}-gui"
NATIVE_GUI_IMAGE="${IMAGE}-gui-native"

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
        "$IMAGE" python /app/cli/main.py

elif [ "$command" = "test" ]; then
    ensure_image
    echo "Running the tests inside the container..."
    docker run --rm --network none "$IMAGE" pytest

elif [ "$command" = "gui" ] || [ "$command" = "gui-web" ]; then
    if [ "$command" = "gui" ]; then
        TARGET="gui-native"
        ACTIVE_GUI_IMAGE="$NATIVE_GUI_IMAGE"
        DISPLAY_ADDRESS="${PHISHREPORT_DISPLAY:-host.docker.internal:0}"
        echo "Building the native-window desktop GUI image..."
    else
        TARGET="gui"
        ACTIVE_GUI_IMAGE="$GUI_IMAGE"
        echo "Building the browser desktop GUI image..."
    fi
    docker build --target "$TARGET" -t "$ACTIVE_GUI_IMAGE" "$(docker_path "$PROJECT_DIR")"

    MOCK_AUTH_NAME=""
    MOCK_AUTH_NETWORK=""
    AUTH_FILE=""
    cleanup_gui_resources() {
        if [ -n "$MOCK_AUTH_NAME" ]; then
            docker stop "$MOCK_AUTH_NAME" >/dev/null 2>&1 || true
        fi
        if [ -n "$MOCK_AUTH_NETWORK" ]; then
            docker network rm "$MOCK_AUTH_NETWORK" >/dev/null 2>&1 || true
        fi
        if [ -n "$AUTH_FILE" ]; then
            rm -f "$AUTH_FILE"
        fi
    }
    trap cleanup_gui_resources EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM

    if [ "$command" = "gui" ] && [ "$(uname -s)" = "Darwin" ]; then
        XAUTH_BIN="$(command -v xauth || true)"
        if [ -z "$XAUTH_BIN" ] && [ -x /opt/X11/bin/xauth ]; then
            XAUTH_BIN="/opt/X11/bin/xauth"
        fi
        if [ -z "$XAUTH_BIN" ]; then
            echo "XQuartz xauth was not found. Install and start XQuartz, then retry."
            exit 1
        fi

        HOST_DISPLAY="${DISPLAY:-:0}"
        XAUTH_RECORDS="$("$XAUTH_BIN" nlist "$HOST_DISPLAY" 2>/dev/null || true)"
        if [ -z "$XAUTH_RECORDS" ]; then
            echo "No X11 authorization cookie was found for $HOST_DISPLAY."
            echo "Start XQuartz and enable 'Authenticate connections' and"
            echo "'Allow connections from network clients' in its Security settings."
            exit 1
        fi

        AUTH_FILE="$(mktemp "$PROJECT_DIR/.phishreport-xauth.XXXXXX")"
        chmod 600 "$AUTH_FILE"
        if ! printf '%s\n' "$XAUTH_RECORDS" \
            | sed 's/^..../ffff/' \
            | "$XAUTH_BIN" -f "$AUTH_FILE" nmerge -; then
            echo "Could not prepare a temporary X11 authorization file."
            exit 1
        fi
        unset XAUTH_RECORDS
    fi

    if [ -n "${PHISHREPORT_API_URL:-}" ]; then
        API_URL="$PHISHREPORT_API_URL"
        if [ "$command" = "gui" ]; then
            if [ -n "$AUTH_FILE" ]; then
                docker run --rm -it \
                    -v "$(docker_path "$AUTH_FILE"):/tmp/.Xauthority:ro" \
                    -e "XAUTHORITY=/tmp/.Xauthority" \
                    -e "DISPLAY=$DISPLAY_ADDRESS" \
                    -e QT_X11_NO_MITSHM=1 \
                    -e "PHISHREPORT_API_URL=$API_URL" \
                    "$ACTIVE_GUI_IMAGE"
            else
                docker run --rm -it \
                    -e "DISPLAY=$DISPLAY_ADDRESS" \
                    -e QT_X11_NO_MITSHM=1 \
                    -e "PHISHREPORT_API_URL=$API_URL" \
                    "$ACTIVE_GUI_IMAGE"
            fi
        else
            docker run --rm -it \
                -p 127.0.0.1:6080:6080 \
                -e "PHISHREPORT_API_URL=$API_URL" \
                "$ACTIVE_GUI_IMAGE"
        fi
    else
        MOCK_AUTH_NAME="${ACTIVE_GUI_IMAGE}-auth-$$"
        MOCK_AUTH_NETWORK="${ACTIVE_GUI_IMAGE}-net-$$"
        docker network create "$MOCK_AUTH_NETWORK" >/dev/null
        echo "Starting the local demo authentication API..."
        docker run --rm -d \
            --name "$MOCK_AUTH_NAME" \
            --network "$MOCK_AUTH_NETWORK" \
            --network-alias phishreport-auth \
            "$ACTIVE_GUI_IMAGE" \
            python -m gui.mock_auth_api --host 0.0.0.0 --port 8000
        API_URL="http://phishreport-auth:8000"
        echo "Demo sign-in: demo@phishreport.test / phishreport-demo"
        if [ "$command" = "gui" ]; then
            echo "Displaying the app through X11 at $DISPLAY_ADDRESS"
            if [ -n "$AUTH_FILE" ]; then
                docker run --rm -it \
                    --network "$MOCK_AUTH_NETWORK" \
                    -v "$(docker_path "$AUTH_FILE"):/tmp/.Xauthority:ro" \
                    -e "XAUTHORITY=/tmp/.Xauthority" \
                    -e "DISPLAY=$DISPLAY_ADDRESS" \
                    -e QT_X11_NO_MITSHM=1 \
                    -e "PHISHREPORT_API_URL=$API_URL" \
                    "$ACTIVE_GUI_IMAGE"
            else
                docker run --rm -it \
                    --network "$MOCK_AUTH_NETWORK" \
                    -e "DISPLAY=$DISPLAY_ADDRESS" \
                    -e QT_X11_NO_MITSHM=1 \
                    -e "PHISHREPORT_API_URL=$API_URL" \
                    "$ACTIVE_GUI_IMAGE"
            fi
        else
            echo "Open http://localhost:6080/vnc.html?autoconnect=true&resize=scale"
            docker run --rm -it \
                --network "$MOCK_AUTH_NETWORK" \
                -p 127.0.0.1:6080:6080 \
                -e "PHISHREPORT_API_URL=$API_URL" \
                "$ACTIVE_GUI_IMAGE"
        fi
    fi
    if [ "$command" = "gui-web" ] && [ -n "${PHISHREPORT_API_URL:-}" ]; then
        echo "Open http://localhost:6080/vnc.html?autoconnect=true&resize=scale"
    fi

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
    for image in "$IMAGE" "$GUI_IMAGE" "$NATIVE_GUI_IMAGE"; do
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
    echo "  gui     run the GUI in a native X11 window (requires XQuartz/VcXsrv)"
    echo "  gui-web build and open the GUI in a browser with noVNC"
    echo "  test    run the tests in the container"
    echo "  shell   build if needed and open a shell inside the container"
    echo "  clean   delete the CLI and GUI images"
fi
