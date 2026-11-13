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

    terminal.read.assert_called_once_with("Choose 1-6: ")


@pytest.mark.parametrize("choice", ["1", "2", "3", "4", "5", "6"])
def test_menu_still_normalizes_numeric_choices(choice):
    terminal = Mock()
    terminal.read.return_value = f" \t{choice}  "

    assert IOManager(terminal).main_menu() == choice


@pytest.mark.parametrize("accepted", ["  /check Mixed CASE  ", " 4 "])
def test_menu_reprompts_invalid_non_commands_before_accepting_input(accepted):
    terminal = Mock()
    terminal.read.side_effect = ["", "7", "ordinary text", accepted]

    assert IOManager(terminal).main_menu() == (
        accepted if accepted.lstrip().startswith("/") else "4"
    )

    assert terminal.read.call_args_list == [
        call("Choose 1-6: "),
        *[call("Invalid choice. Please choose 1-6: ")] * 3,
    ]


@pytest.mark.parametrize("error_type", [EOFError, KeyboardInterrupt])
@pytest.mark.parametrize("invalid_first", [False, True])
def test_menu_propagates_input_cancellation(error_type, invalid_first):
    terminal = Mock()
    terminal.read.side_effect = (["invalid"] if invalid_first else []) + [error_type()]

    with pytest.raises(error_type):
        IOManager(terminal).main_menu()
