"""Menu input retains command payloads for application-level routing."""

from unittest.mock import Mock, call

import pytest

from phishreport.io import IOManager


@pytest.mark.parametrize("text", [
    "/check URGENT  Payment ", "  /check Keep Case\nMore text  ",
    "/help", "\t/unknown Content ", "/", "/CHECK Text",
])
def test_menu_returns_slash_input_untouched(text):
    terminal = Mock()
    terminal.read.side_effect = [text]

    assert IOManager(terminal).main_menu() == text

    terminal.read.assert_called_once_with("Choose 1-7: ")


def test_menu_lists_the_export_action_before_quit():
    terminal = Mock()
    terminal.read.return_value = "7"

    assert IOManager(terminal).main_menu() == "7"

    assert terminal.write.call_args_list == [
        call("\n=== PhishReport ==="),
        call("1. Check a new message (Manual Input)"),
        call("2. Import the newest emails from your saved folder"),
        call("3. Upload an .eml in a browser"),
        call("4. View saved reports"),
        call("5. Summarize saved reports"),
        call("6. Filter and export saved reports"),
        call("7. Quit"),
    ]


@pytest.mark.parametrize("choice", ["1", "2", "3", "4", "5", "6", "7"])
def test_menu_still_normalizes_numeric_choices(choice):
    terminal = Mock()
    terminal.read.return_value = f" \t{choice}  "

    assert IOManager(terminal).main_menu() == choice


@pytest.mark.parametrize("accepted", ["  /check Mixed CASE  ", " 4 "])
def test_menu_reprompts_invalid_non_commands_before_accepting_input(accepted):
    terminal = Mock()
    terminal.read.side_effect = ["", "8", "ordinary text", accepted]

    assert IOManager(terminal).main_menu() == (
        accepted if accepted.lstrip().startswith("/") else "4"
    )

    assert terminal.read.call_args_list == [
        call("Choose 1-7: "),
        *[call("Invalid choice. Please choose 1-7: ")] * 3,
    ]


@pytest.mark.parametrize("error_type", [EOFError, KeyboardInterrupt])
@pytest.mark.parametrize("invalid_first", [False, True])
def test_menu_propagates_input_cancellation(error_type, invalid_first):
    terminal = Mock()
    terminal.read.side_effect = (["invalid"] if invalid_first else []) + [error_type()]

    with pytest.raises(error_type):
        IOManager(terminal).main_menu()
