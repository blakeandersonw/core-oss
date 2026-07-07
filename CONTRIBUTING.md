# Contributing to StarterStack

Thanks for your interest in contributing! This guide will help you get started.

## Development Setup

Follow the [Quick Start](./README.md#quick-start) to get both services running locally. You only need Supabase for most development work.

## Project Structure

- **`core-api/`** — Python/FastAPI backend. See [core-api/README.md](./core-api/README.md) for architecture details.
- **`core-web/`** — React/Vite frontend. See [core-web/README.md](./core-web/README.md) for frontend details.

## Making Changes

### Backend (core-api)

```bash
cd core-api

# Run tests
make test

# Type checking
make typecheck

# Lint
make lint

# Format
make format

# Run all checks
make check
```

**Pattern**: Routes go in `api/routers/`, business logic in `api/services/`, shared clients in `lib/`.

### Frontend (core-web)

```bash
cd core-web

# Dev server with hot reload
npm run dev

# Lint
npm run lint

# Type check
npx tsc -b

# Build
npm run build
```

**Pattern**: Feature components in `src/components/`, state in `src/stores/` (Zustand), API calls through `src/api/client.ts`.

## Pull Requests

1. Fork the repo and create a branch from `main`
2. Make your changes
3. Ensure tests pass (`make check` in core-api, `npm run lint` in core-web)
4. Write a clear PR description explaining what changed and why
5. Keep PRs focused — one feature or fix per PR

## Commit Messages

Use clear, descriptive commit messages:

```
Add project board filtering by label
Fix calendar event timezone offset for UTC+N zones
Update email sync to handle Gmail batch API rate limits
```

## Database Migrations

If your change requires schema modifications:

```bash
cd core-api
supabase migration new my_migration_name
```

Write idempotent SQL — use `IF NOT EXISTS`, `DROP ... IF EXISTS` before `CREATE`. See `core-api/supabase/README.md` for patterns.

## Environment Variables

If you add a new environment variable:

1. Add it to `core-api/api/config.py` (with a sensible default or empty string)
2. Add it to the appropriate `.env.example` with a comment
3. Document which tier it belongs to (required / optional / feature-specific)

## Code Style

- **Python**: Follow existing patterns. Pydantic models for validation. Async where the service layer is async.
- **TypeScript**: Follow existing patterns. Zustand for state. `api<T>()` client for API calls.
- No unnecessary abstractions. Three similar lines > premature helper function.

## Reporting Issues

Open an issue on GitHub with:
- What you expected to happen
- What actually happened
- Steps to reproduce
- Your environment (OS, Node/Python version, browser)

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.
