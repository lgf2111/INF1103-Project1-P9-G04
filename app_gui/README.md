# PhishReport on Telegram

## Configure the bot

Use the bot token provisioned for the team and the numeric chat ID from the
intended user's private conversation with that bot. To get the ID, send the
bot `/start` and check `message.chat.id` in the Telegram Bot API `getUpdates`
response before the runner starts polling. Confirm that `message.chat.type`
is `private`. Keep the token and raw response private, and use one poller
per token.

Create an ignored `.env.telegram` file in the repository root:

```dotenv
TELEGRAM_BOT_TOKEN=<existing bot token>
TELEGRAM_ALLOWED_CHAT_ID=<positive private chat ID>
```

## Run in Docker

From Bash on macOS or Linux, or Git Bash/WSL on Windows:

```bash
bash run.sh telegram
```

The helper builds the `telegram` target if needed and mounts
`.phishreport-data/` at `/data` read-only. The check uses `/data/reports.json`,
the same history location used by the CLI Docker helper. The bot uses
outbound long polling and needs no published ports.

For a first run with empty history, these Docker commands also work
directly from PowerShell:

```text
docker build --target telegram -t phishreport-telegram .
docker run --rm --env-file .env.telegram phishreport-telegram
```

To test with existing history using the direct command, add
`--mount "type=bind,source=${PWD}/.phishreport-data,target=/data,readonly"`
before the image name. Use an existing directory. Rebuild after changing the
code if you already have the image.

## Run locally

With Python 3.14 and uv installed, export both settings into the current shell
and run this command from the repository root:

```bash
uv run --python 3.14 --no-project --with-requirements requirements.txt python -m app_gui.main
```

The local launcher reads `reports.json` in the working directory. To choose
another file, set `PHISHREPORT_REPORTS_PATH`.

## Live acceptance check

1. Start the container with the provisioned settings.
2. In the configured private chat, send `/start`. Confirm the PhishReport
   welcome has one **Check connection** button.
3. Tap it. Confirm Telegram clears the tap indicator and the bot replies
   **Connection check passed.** Missing or empty history should pass.
4. If available, try `/start` from a different chat and confirm it receives
   no menu. The offline suite covers read failures and checks that history
   bytes are preserved.

## Add the next handler

Add an async method to `TelegramIOManager` in `telegram_io_manager.py`.
Use the same private-chat check before accessing any application data.
Register the method in `main.py` using a command or a distinct callback
pattern. Keep application work in shared Python managers, and test the
handler with fake updates in `tests/test_telegram_gui.py`.

Manual assessment, `.eml` upload, history screens, and Gmail are follow-up work.
