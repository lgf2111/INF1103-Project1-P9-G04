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
# First time only: make it runnable with  chmod +x docker.sh
# You need Docker Desktop open, and a .env file with your GROQ_API_KEY.

IMAGE="phishreport"

# stop and show the error if any command fails
set -e

command="$1"

if [ "$command" = "build" ]; then
    echo "Building the $IMAGE image..."
    docker build -t "$IMAGE" .
    echo "Done. Now run:  ./docker.sh run"

elif [ "$command" = "run" ]; then
    if [ ! -f .env ]; then
        echo "No .env file found. Make one with:  GROQ_API_KEY=your_key"
        exit 1
    fi
    echo "Starting the app (Ctrl+C to quit)..."
    # --env-file passes your key into the container; -it lets you type answers;
    # -p publishes the file-upload page (option 3) so your browser can reach it.
    docker run --rm -it -p 8000:8000 --env-file .env "$IMAGE"

elif [ "$command" = "test" ]; then
    echo "Running the tests inside the container..."
    docker run --rm "$IMAGE" pytest

elif [ "$command" = "shell" ]; then
    # Open an interactive shell INSIDE the container so you can look around
    # (Docker containers have no SSH; this is how you "get inside" one).
    # Loads .env if you have it, so your key is available in there too.
    echo "Opening a shell inside the container (type 'exit' to leave)..."
    if [ -f .env ]; then
        docker run --rm -it --env-file .env "$IMAGE" /bin/bash
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
