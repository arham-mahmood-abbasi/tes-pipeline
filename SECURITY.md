# Security Policy

## Supported versions

This project currently ships from `main` only. Security fixes will be tagged
`vX.Y.Z` once the first stable release is cut.

## Reporting a vulnerability

Please **do not** open public GitHub issues for security problems. Email instead:

**arhamabbasi915@gmail.com** — subject line: `[tes-pipeline security]`

You should receive an acknowledgement within 72 hours. If you don't, please
follow up.

## Reporting a leaked secret

If you find an API key, service-account JSON, or other credential exposed in
this repository or its git history, treat it as a security incident:

1. Email **arhamabbasi915@gmail.com** with the commit SHA and file path.
2. Do not open a public issue or pull request that names the secret.
3. The credential will be rotated immediately upon receipt.

## Secrets-handling rules for contributors

- **Never** commit a real API key, OAuth client secret, or service-account JSON.
- The only acceptable values for sensitive fields are placeholders — see
  [`.env.example`](.env.example).
- `pre-commit` runs `gitleaks` on every commit, and CI runs it on every push
  and pull request. Both must pass before merge.
- If `gitleaks` flags a string that is genuinely safe (e.g. a test fixture),
  add an inline `# gitleaks:allow` comment and explain why in the PR description.
