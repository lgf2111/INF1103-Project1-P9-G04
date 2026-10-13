# My submission checks

I submit `main` by **14 October 2026, 23:59 Singapore time**. I use the final
integrated commit below, rather than a feature branch or an old CI run.

## Before I submit

- [ ] I record `git rev-parse HEAD` on up-to-date `main` and its successful CI URL.
- [ ] I confirm the report and statement PDFs are tracked in `submission/`.
- [ ] I obtain instructor sign-off for the problem statement and retain the
  Initial Details submission receipt. The current statement does not prove approval.
- [ ] I confirm every member and lab-in-charge has the required repository access
  and that each member cloned it.
- [ ] Every member verifies the same final commit inside Docker and records
  build/test/run, real-email assessment and restart results with their name.
- [ ] I clarify fresh-model repeatability and saved-history API scope with the instructor.
- [ ] I rehearse the submitted version and confirm each member can explain their part.
- [ ] I submit the required repository/materials through the designated course route
  and retain the submission receipt before the deadline.

## My repeatable verification

From current `main`, I run `./docker.sh build`, `./docker.sh test` and
`./docker.sh run` in Bash (Git Bash on Windows). Docker Desktop must be running;
the live assessment needs my configured API key. I never commit that key.

For a real input I select option 2, `/emails`, then `sample-1.eml`, or upload
the same file using option 3 at `http://localhost:8000`. I answer exposure
questions for the scenario I am testing, without visiting embedded links or
opening attachments. I verify reasons, numeric score, priority and guidance,
and check there is no local-save warning. A model response may vary; 45/MEDIUM
was an observed no-exposure result, not a mandatory answer for every live call.

I quit and restart the container, select option 4 and confirm the same stored
result. Docker uses `.phishreport-data/reports.json`; host Python uses the
working directory. I do not confuse these two locations.

I run failure demonstrations in isolated temporary storage: invalid menu input
must re-prompt; an unsupported or malformed real-email derivative must be
rejected; missing/invalid AI must fail without saving; corrupt JSON or historical
field types must preserve bytes and leave the menu usable. I use the offline
regressions for transport/write failures rather than altering production history.

## My demonstration sequence

1. I show the four physical manager files and their required functions.
2. I trace a real .eml from parsed input through the JSON prompt, validated
   findings, first-match rule and saved version-2 outcome. I keep credentials hidden.
3. I explain the rule combining suspicion and credential-request AI fields, the
   35/70 thresholds, reasons and the difference between policy score and probability.
4. I show validation/failure recovery and distinguish AI failure from save failure.
5. I restart Docker and show persistent history, then run the offline tests.
6. Each member explains their own contribution and one integration boundary.

The engineering report's diagram and exception matrix share page 2. Our latest
local evidence is 694 offline Docker tests and 683 Windows tests with 11 POSIX
skips; this does not replace another member's final-machine evidence.
