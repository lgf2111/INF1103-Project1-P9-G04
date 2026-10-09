# Runs the app in Docker so it works the same on everyone's laptop.
FROM python:3.12-slim

WORKDIR /app

# install the requirements first
COPY requirements.txt .
RUN pip install -r requirements.txt

# copy the code in
COPY . .

# The file-upload option serves a one-shot page on port 8000; publish it so the
# host browser can reach it: docker run -p 8000:8000 ...
EXPOSE 8000

# run the app by default. pass your key and publish the upload port like:
#   docker run --rm -it -p 8000:8000 -e GROQ_API_KEY=xxx phishreport
# to run the tests instead:  docker run --rm phishreport pytest
CMD ["python", "app/main.py"]
