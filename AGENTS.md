# Repository instructions

## Run every test before every push

Immediately before each `git push`, run `pnpm run test:pre-push` from the repository root. This command runs the complete default Python test suite and every pnpm workspace test suite. Focused tests used during development do not replace this final gate.

Do not push while any required test fails. Tests that are explicitly environment-gated may self-skip when their documented credential, platform, toolchain, or opt-in flag is unavailable. When a change affects an environment-gated surface, also run that surface's documented test command whenever its prerequisites are available.

Report the exact test commands run and their outcomes when handing work back to the user.
