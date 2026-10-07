# io_manager.py
# All input() and print() live here. OWNER: Lee Guan Feng.


def main_menu():
    print("\n=== PhishReport ===")
    print("1. Check a new message")
    print("2. View saved reports")
    print("3. Quit")

    choice = input("Choose 1-3: ").strip()

    while choice not in ("1", "2", "3"):
        choice = input("Invalid choice. Please choose 1-3: ").strip()

    return choice


def collect_input():
    channel = get_channel()
    sender = get_sender()
    message = get_message()

    has_link, link = get_link_information()
    has_file, file_name = get_file_information()

    user_actions = collect_user_actions(has_link, has_file)

    return {
        "channel": channel,
        "sender": sender,
        "message": message,
        "has_link": has_link,
        "link": link,
        "has_file": has_file,
        "file_name": file_name,
        "clicked": user_actions["clicked"],
        "downloaded": user_actions["downloaded"],
        "submitted_category": user_actions["submitted_category"],
    }

def ask_yes_no(question):
    answer = input(question).strip().lower()

    while answer not in ("y", "yes", "n", "no"):
        answer = input("Please type yes/y or no/n: ").strip().lower()

    return answer in ("y", "yes")

def get_channel():
    channel = input("Enter channel (Email/SMS/Chat): ").strip().lower()

    while channel not in ("email", "sms", "chat"):
        channel = input(
            "Invalid channel. Please enter Email, SMS, or Chat: "
        ).strip().lower()

    return channel

def get_sender():
    sender = input(
        "Enter sender information (press Enter if unknown): "
    ).strip()

    if sender == "":
        return None

    return sender

def get_message():
    message = input("Enter the suspicious message: ").strip()

    while message == "":
        message = input(
            "Message cannot be blank. Please enter the suspicious message: "
        ).strip()

    return message

def get_link_information():
    has_link = ask_yes_no("Was a link included? (yes/no): ")

    if not has_link:
        return False, None

    link = input("Enter the link: ").strip()

    while link == "":
        link = input(
            "Link cannot be blank. Please enter the link: "
        ).strip()

    return True, link

def get_file_information():
    has_file = ask_yes_no("Was a file included? (yes/no): ")

    if not has_file:
        return False, None

    file_name = input("Enter the file name: ").strip()

    while file_name == "":
        file_name = input(
            "File name cannot be blank. Please enter the file name: "
        ).strip()

    return True, file_name

def get_submitted_category():
    submitted = input(
        "Did you give a password or code? (password/otp/no): "
    ).strip().lower()

    while submitted not in ("password", "otp", "no"):
        submitted = input(
            "Please type password, otp or no: "
        ).strip().lower()

    if submitted == "no":
        return None

    return submitted

def collect_user_actions(has_link, has_file):
    if has_link:
        clicked = ask_yes_no("Did you click the link? (yes/no): ")
    else:
        clicked = False

    if has_file:
        downloaded = ask_yes_no("Did you download the file? (yes/no): ")
    else:
        downloaded = False

    submitted_category = get_submitted_category()

    return {
        "clicked": clicked,
        "downloaded": downloaded,
        "submitted_category": submitted_category,
    }

def display_result(result):
    if not result:
        print("\nNo assessment available.")
        return

    priority = (result.get("priority") or "unavailable").replace(
        "_", " "
    ).title()
    print("\n=== Assessment ===")
    print("Priority:", priority)
    print("Rule-based score:", result.get("score", "Unavailable"))

    if result.get("reasons"):
        print("\nReasons:")
        for reason in result["reasons"]:
            print(" -", reason)

    print("\nRecommended actions:")
    for number, step in enumerate(result.get("checklist", []), start=1):
        print(f"{number}. {step}")


def display_record(record):
    print("\n=== Report details ===")
    channels = {"email": "Email", "sms": "SMS", "chat": "Chat"}
    print("Channel:", channels.get(record.get("channel"), "Unknown"))
    print("Sender:", record.get("sender") or "Unknown")
    print("Message:")
    print(record.get("message") or "No message recorded.")
    print("Included link:", record.get("link") or "None reported")
    print("Included file:", record.get("file_name") or "None reported")

    answers = {True: "Yes", False: "No", None: "Not recorded"}
    print("Clicked link:", answers[record.get("clicked")])
    print("Downloaded file:", answers[record.get("downloaded")])
    submitted = record.get("submitted_category")
    labels = {"password": "Password", "otp": "One-time code"}
    print("Information submitted:", labels.get(submitted, submitted or "None reported"))

    display_result(record.get("result") or {})


def display_list(records):
    if not records:
        print("No saved reports yet.")
        return

    print("\n=== Saved reports ===")
    for number, record in enumerate(records, start=1):
        result = record.get("result") or record
        priority = (result.get("priority") or "unavailable").replace(
            "_", " "
        ).title()
        channels = {"email": "Email", "sms": "SMS", "chat": "Chat"}
        channel = channels.get(record.get("channel"), "Unknown")
        score = result.get("score")
        if score is None:
            score = "Unavailable"
        preview = " ".join((record.get("message") or "").split())
        if len(preview) > 50:
            preview = preview[:47] + "..."
        print(f"{number}. {channel} | {priority} | Score: {score}")
        print(f"   {preview}")


def show_message(text):
    print(text)
