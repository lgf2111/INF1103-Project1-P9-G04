# Exception-handling matrix

How PhishReport fails, what the caller sees, and which test proves it. The rule
throughout: a failure never becomes a LOW result and never invents data. Every
boundary raises a typed failure from `phishreport/errors.py` with a fixed
`user_message`; the original exception is kept only as `__cause__` for developers and
never printed.

## AI and provider failures (API connection failure, malformed API response)

| Failure | Trigger | Raised as | User message | What the application does | Test |
| --- | --- | --- | --- | --- | --- |
| API connection failure | DNS/connection error from the provider (`ProviderFailureReason.TRANSPORT`) | `ProviderFailure` then `AIUnavailable` | "AI could not complete the assessment. Please try again." | No retry that duplicates a request, nothing saved, the session stays usable | `tests/core/test_error_handling_matrix.py::test_public_ai_failure_has_safe_message_without_mutating_input` |
| API timeout | Socket timeout (`ProviderFailureReason.TIMEOUT`) | `ProviderFailure` then `AIUnavailable` | "The check failed: could not reach the AI service. Check your internet connection and try again." | Same as above; the cause is preserved but not shown | `tests/core/test_ai_core.py::test_assess_maps_provider_failure_without_retry_and_remains_ready` |
| Rate limiting | HTTP 429 (`ProviderFailureReason.HTTP`) | `ProviderFailure` then `AIUnavailable` | "The check failed: the AI service is busy (rate limited). Try again shortly." | Assessment is abandoned; no partial report is written | `tests/cli/test_assessment_errors.py::test_typed_ai_failure_uses_provider_guidance` |
| Provider outage | HTTP 5xx | `ProviderFailure` then `AIUnavailable` | "The check failed: the AI service is temporarily unavailable. Try again shortly." | Same; the CLI and bot both return to their prompt | `tests/cli/test_assessment_errors.py::test_typed_ai_failure_uses_provider_guidance` |
| Missing configuration | No API key or unusable settings (`ProviderFailureReason.CONFIGURATION`) | `ProviderFailure` then `AIUnavailable` | "AI could not complete the assessment. Please try again." | Fails before any HTTP request | `tests/core/test_ai_error_translator.py::test_provider_metadata_selects_safe_guidance` |
| Malformed API response | Reply is not JSON, is wrapped in an unexpected envelope, or the findings fail schema or source checks | `InvalidInput` (cause `ValueError`) | "Invalid input. Please revise it and try again." | The AI is called once, nothing is scored, nothing is saved | `tests/core/test_ai_core.py::test_assess_rejects_invalid_completion_without_retry` |

## Input failures (invalid user input)

| Failure | Trigger | Raised as | User message | What the application does | Test |
| --- | --- | --- | --- | --- | --- |
| Invalid user input | Blank message, unsupported channel, malformed record fields | `InvalidInput` | "Invalid input. Please revise it and try again." | Validation runs before the AI; the record is not mutated | `tests/core/test_ai_core.py::test_assess_rejects_bad_input_before_completion` |
| Invalid assessment record | Record or findings rejected by the logic validator | `InvalidInput` (cause `AssessmentValidationError`) | "Invalid input. Please revise it and try again." | Both inputs stay unchanged; the caller re-prompts | `tests/core/test_error_handling_matrix.py::test_real_logic_validation_has_typed_cause_without_mutating_inputs` |
| Oversized email | `.eml` larger than 2 MiB | `ValueError` at the reader, `InvalidInput` at the boundary | "Invalid input. Please revise it and try again." | Import stops before parsing or assessment | `tests/core/test_io_manager.py::test_io_manager_read_eml_details_rejects_over_2_mib` |
| Hostile MIME structure | Too many parts, nesting deeper than 32, missing boundary | `ValueError` at the reader, `InvalidInput` at the boundary | Same as above | Reader rejects the file instead of partially assessing it | `tests/core/test_io_manager.py::test_io_manager_read_eml_details_rejects_too_many_mime_parts` |
| Over-long message | More than 50,000 characters after decoding | `ValueError` at the reader, `InvalidInput` at the boundary | Same as above | Nothing is sent to the AI | `tests/core/test_io_manager.py::test_io_manager_read_eml_details_rejects_message_over_50000_chars` |

## Persistence failures (corrupt or missing data file)

| Failure | Trigger | Raised as | User message | What the application does | Test |
| --- | --- | --- | --- | --- | --- |
| Missing data file | No `reports.json` yet | not an error | none | History starts empty; the first save creates the file | `tests/core/test_data_manager.py::test_data_manager_startup` |
| Corrupt data file | Invalid JSON, duplicate fields, non-list root, record that fails validation | `StorageFailure` (cause `ValueError`) | "Could not access local report history. Please try again." | The existing file is left byte-for-byte intact; no partial rewrite | `tests/core/test_data_manager.py::test_data_manager_corrupt_history_is_preserved` |
| Write failure | Permission denied, disk full, failed atomic replace | `StorageFailure` (cause `OSError`) | "Could not access local report history. Please try again." | Previous history preserved, temporary file cleaned up, the assessment is still shown | `tests/core/test_data_manager.py::test_data_manager_failed_atomic_replace_preserves_old_history` |
| Invalid report rejected | Schema violation before storage is touched | `InvalidInput` | "Invalid input. Please revise it and try again." | No storage call is made at all | `tests/core/test_error_handling_matrix.py::test_invalid_new_report_is_rejected_before_any_storage_io` |
| Corrupt feedback file | `feedback.json` unreadable or malformed | `StorageFailure` | "Could not access local report history. Please try again." | File preserved; the assessment itself is unaffected | `tests/core/test_error_handling_matrix.py::test_corrupt_feedback_read_preserves_file` |
| Rejected feedback | Duplicate identifier, unknown category, invalid assessment id | `FeedbackRejected` | "Feedback could not be accepted. Please check the details." | Saved feedback and the assessment context are unchanged | `tests/core/test_error_handling_matrix.py::test_public_feedback_rejection_preserves_saved_feedback_and_context` |

## Interface boundaries

| Failure | Trigger | Raised as | User message | What the application does | Test |
| --- | --- | --- | --- | --- | --- |
| Telegram assessment failure | Typed failure while assessing a chat message | `AssessmentError` family | The typed `user_message` | One safe reply, no save, no follow-up question | `tests/bot/test_bot_assessment_errors.py::test_typed_assessment_failure_is_safe_and_stops_followup` |
| Gmail monitor failure | Typed assessment failure while polling an inbox | `AssessmentError` family | Logged summary only; the chat is not spammed | The mailbox UID is not advanced, so the message is retried next cycle | `tests/bot/test_monitor_assessment_errors.py::test_typed_assessment_failure_keeps_uid_without_rechecking` |
| Save failure after a result | Local history cannot be written | `StorageFailure` | "Could not access local report history. Please try again." | The result is still displayed; the feedback prompt is skipped | `tests/cli/test_assessment_errors.py::test_typed_save_failure_keeps_result_without_feedback` |

## Deliberate non-handling

A programmer error (`TypeError`, `KeyError`, `AttributeError`) is never converted into a
user message. Those propagate so a defect fails loudly in tests instead of being hidden
behind a friendly sentence.
