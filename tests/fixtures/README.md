# Essential real-email regression fixtures

These three public phishing emails are retained for MIME parsing, empty-body
alternatives, browser upload byte preservation, history compatibility and the
separate automated demo. They are test dependencies, not a demonstration dataset
or detection benchmark. Removing them would break meaningful regression tests.

Source: [rf-peixoto/phishing_pot](https://github.com/rf-peixoto/phishing_pot/tree/2933c0341b1248678c1e246b36d352add2edf0f1/email),
commit `2933c0341b1248678c1e246b36d352add2edf0f1`, files
`email/sample-1.eml`, `email/sample-2.eml`, `email/sample-3.eml`.
Original bytes are retained. Never follow their targets or execute attachments.
The tests parse them as inert data and use isolated temporary storage.

Application acceptance/demo emails use these real examples. Small constructed
protocol/type/encoding inputs in unit tests are fault probes, not additional
sample email datasets or evidence of detection accuracy. Hardcoded AI findings
are controlled offline responses, not claimed live verdicts.
