# Contributing

Thank you for helping improve Space Debris SSA Tool. This project is an educational
platform and must not be represented as an operational collision-avoidance system.

## Before opening a change

1. Search existing issues and open one for substantial behavior or methodology changes.
2. Keep generated reports, credentials, local databases, and `.env` files out of commits.
3. Create a focused branch from `main` and include tests with behavior changes.

## Local checks

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -W error

cd web
npm ci
npm run lint
npm run typecheck
npm test
npm run build
```

Use `npm run test:e2e` after installing Playwright Chromium with
`npx playwright install chromium`.

## Scientific changes

Describe assumptions, reference frames, input provenance, uncertainty treatment, and
validation evidence. Clearly distinguish illustrative approximations from validated
methods. Never remove the non-operational disclaimer without a documented independent
validation process.

## Pull requests

Explain the user-visible outcome, testing performed, and any deployment or migration
impact. Do not include secrets or personally identifiable information.
