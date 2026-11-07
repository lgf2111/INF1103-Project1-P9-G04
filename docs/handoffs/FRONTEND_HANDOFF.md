# Frontend handoff for Telegram

The connection milestone opens a PhishReport welcome on `/start` and
provides one **Check connection** button. The authorized private chat gets
a read-only history check and a short status message. Use the
[Telegram run guide](../../app_gui/README.md) to run it or add a handler.

## Next milestone

The existing CLI supports manual Email, SMS and Chat checks, `.eml` import,
exposure questions, results, and local history. Keep it usable while moving
these interactions into Telegram.

1. Add **Check a message** to the home menu. Let the user paste text or
   attach one `.eml`. Reuse the shared parser and its 2 MiB file limit.
2. Collect the relevant exposure answers. Ask about clicking or downloading
   when applicable and ask about password or one-time code disclosure.
   Treat unanswered questions as unanswered.
3. Before confirmation, explain where the message is processed and what
   the application stores. Use the confirmed policy from the service owners.
4. Acknowledge the tap, show progress, and prevent duplicate submissions.
   If a check fails, keep the draft available for correction or retry.
5. Display the returned priority, reasons, and recommended actions. Label
   priority in text and keep the score secondary. Explain that a LOW result
   does not guarantee safety. Offer another check or a return to Home.
6. Add **Recent checks** once the history contract is agreed. Give empty
   history and read failure separate messages. Show the report details only
   when the user opens a report in the authorized chat.

Use inline buttons for choices, confirmation, and navigation. Provide
**Back**, **Home**, or **Cancel** where applicable. Keep long operations off
the bot's event loop and exercise the flow offline with fake services and
Telegram updates.

Use the [backend handoff](BACKEND_HANDOFF.md) to agree on request fields,
validated results, and safe error messages. The Telegram handlers should
call that Python service in the same process.
