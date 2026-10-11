# QQ-Bot repository instructions

Read AGENTS.md and docs/index.md, docs/status.md, docs/requirements.md,
docs/decisions.md before changing files. These are the shared source of truth;
task acceptance lives in docs/backlog.md. Use the repository checkout root in
cloud environments; the Windows path in AGENTS.md describes the user's local
workspace and must not be hard-coded into new code or CI.

This is a Python standard-library / SQLite project with a native HTML/CSS/JS
frontend. The installed development baseline is Python 3.14.7. There is no pip
dependency installation required for the current test suite.

Run from the repository root:

```sh
python -m unittest discover -s tests -v
python qq_bot.py --help
git diff --check
```

Tests use synthetic fixtures and temporary databases. Loopback HTTP servers
are part of the tests; they do not connect to QQ or external AI. Do not start
`demo`, `serve`, or `probe-serve` as background services in CI. The existing
100-test result is historical evidence, not proof that your change passes.
Record actual commands, results, operating system and Python version.

Work only within the assigned task's file scope. Make a focused branch and PR;
do not push directly to main, merge your own PR, force-push, weaken tests,
remove failures or expand dependencies to make a check green. Report a scope
blocker instead of silently changing application behavior. Do not add tests
that merely reproduce implementation details.

Never read/upload real chats, credentials, QR codes, private QQ databases or
ignored data/, storage/, exports/, backups/, logs/ content. Do not install or
start NapCat/QQ, fetch media/history, call external AI from the application,
send notifications, execute deletion, deploy, or enable paid overage. Existing
trial approval does not remove the license/retention prerequisites.

Review priorities: account/group boundaries, evidence correctness, expiry and
reference behavior, idempotence/recovery, static errors without body leaks,
thread/socket cleanup, loopback authentication and asynchronous UI state.
Follow the assigned scope and distinguish suggestions from reproducible bugs.
Update affected documentation incrementally; do not replace existing files to
hide changes. Implementation and automated tests are not user acceptance.
