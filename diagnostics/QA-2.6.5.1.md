# ZRE Core 2.6.5.1 — persistent TEST installation

Base: 6239cdc2a24635f0d2ef4a82e1b7fab2a42af220. Main and stable releases unchanged.

TEST installation writes .zre-build.json atomically with program files, retaining the exact source commit, version, channel and web/server SHA-256 hashes. Normal and background updater return without consulting main in TEST. Explicit Restore Stable installs immutable main code, commits STABLE state and resumes normal updates. Installation controllers remain locally compatible with the older stable bridge; all stable telemetry and web assets come unchanged from main.

The existing start_dashboard.bat starts the same bridge via a small identity wrapper. It refuses an occupied 8765, records/verifies PID, executable, root, version and commit before opening the browser, and never reuses an unrelated process. The installer diagnoses Win32 process command/path and remembers the installation root, with automatic unique-installation discovery; ambiguous installs fail rather than guessing. The TEST UI receives runtime identity over the existing WebSocket; no extra socket or telemetry engine.

Local QA: 234 Python tests, all frontend regressions, compileall and diff --check. Four new tests cover frozen TEST/no network, invalid local state, state protection and transactional rollback.

Windows acceptance is checked by the existing workflow's windows-test-install job. It installs into a stable 2.6.5 folder, executes the SAME start_dashboard.bat twice, verifies actual listener PID/executable/root, serves/compares HTML/JS/CSS, opens Chromium and verifies the runtime/commit label received through the real WebSocket, waits 125 seconds on the second runtime, rejects conflicting launcher/installer attempts, restores stable 2.6.5, restarts and checks data markers. The job executes PowerShell on Windows and parses both scripts before running them; its outcome is the release evidence, not an assertion of execution on the user's PC.

No access to the user's PC or iRacing. Installed/runtime identity must be verified by the supplied local installer. The code remains a test build; no main merge or stable release.
