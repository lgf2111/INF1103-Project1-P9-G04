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
    # ask the user about the message and what they did
    message = input("Paste the suspicious message: ").strip()
    while message == "":
        message = input("Message cannot be empty. Paste it again: ").strip()

    submitted = input("Did you give a password or code? (password/otp/no): ").strip()
    while submitted not in ("password", "otp", "no"):
        submitted = input("Please type password, otp or no: ").strip()
    if submitted == "no":
        submitted = None

    clicked = ask_yes_no("Did you click a link? (y/n): ")
    downloaded = ask_yes_no("Did you download a file? (y/n): ")

    return {
        "message": message,
        "submitted_category": submitted,
        "clicked": clicked,
        "downloaded": downloaded,
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
def display_result(result):
    print()
    print("Priority:", result["priority"])
    print("Score:", result["score"])
    print("What to do:")
    for step in result["checklist"]:
        print(" -", step)


def display_list(records):
    if not records:
        print("No saved reports yet.")
        return
    print()
    for i, record in enumerate(records, start=1):
        result = record.get("result", {})
        print(i, "-", result.get("priority", "?"), "-", record.get("message", "")[:50])


def show_message(text):
    print(text)
