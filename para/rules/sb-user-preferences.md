# User Preferences

**MANDATORY. NO EXCEPTIONS.** At the start of EVERY session, you MUST run the Pre-Session Gate below before responding to the user's first request. Skipping the gate is a rule violation, even when the first request "obviously doesn't need preferences."

## Pre-Session Gate

| Step | Requirement |
|------|-------------|
| 1. Probe | Attempt to read `.user/profile/preferences.md`. |
| 2. Apply | If the file exists, load its contents and apply them throughout the conversation — every response, every tool call, every output. |
| 3. Skip | If the file does NOT exist, skip silently and proceed. Graceful degradation — no warnings, no errors. |

The gate fires ONCE per session, before the first user-facing response. If the file is updated mid-session, the next session picks it up.

## Red Flags — STOP and Run the Gate

| Thought | Action |
|---------|--------|
| "The user just asked a simple question — no need to load preferences" | STOP. Probe the file. Preferences may change tone, format, or routing for ANY response. |
| "I already loaded preferences in a previous session" | STOP. Sessions don't share state. Probe again. |
| "There's no `.user/profile/` folder visible" | STOP. Probe the path anyway — file-not-found is the correct skip path, not preemptive skip. |
| "Preferences are about formatting, not behavior — I'll skip" | STOP. Formatting IS behavior. Probe and apply. |
