# Dedicated OpenAI Key Revocation Runbook

Status: instruction template only. Key creation, reading, validation, rotation, or revocation is not authorized by this file.

1. Stop or disable new AI Chat attempts server-side while deterministic pages remain available.
2. The user or a separately authorized security process revokes the dedicated Demo Key at the provider first.
3. Confirm only presence/absence and stable provider status; never copy the Key into chat, a command line, a file, a log, evidence, or Git.
4. Remove the corresponding Azure Container App secret setting using the exact authorized target and command.
5. Restart the application if required and verify deterministic pages still work while AI fails safely with the approved error state.
6. Record timestamp, target identifier, and result without the secret value.

If provider outcome is uncertain, treat the Key as potentially active and keep the revocation task open. No automatic retry is permitted.
