---
name: backend-best-practices
description: Backend development best practices covering API design, security, database work, error handling, and Git/GitHub workflow rules. Use this skill whenever the user asks to build, modify, review, or debug any backend code — Laravel/PHP, Node.js, or Python APIs, controllers, models, migrations, authentication, or server-side logic — even if they don't say "best practices". ALWAYS use this skill before committing or pushing code to GitHub, because it contains mandatory Git identity and credential rules.
---

# Backend Development Best Practices

Standards to follow whenever writing, reviewing, or shipping backend code for this user's projects (primary stack: Laravel + SQLite/MySQL, with some Node.js and Python).

## 1. Git & GitHub Rules (MANDATORY — read before any commit/push)

These rules exist so that ONLY the user's own GitHub account appears in the repository history. Claude must never appear as an author, co-author, or contributor.

1. **Never add Claude attribution to commits.** Do NOT include any of the following in commit messages:
   - `Co-Authored-By: Claude <...>`
   - `Generated with Claude Code` or similar footers
   - Any `Co-Authored-By` trailer that is not explicitly requested by the user
2. **Use the user's own Git identity.** Before committing, verify the identity:
   ```bash
   git config user.name
   git config user.email
   ```
   These must match the user's own GitHub account (the account already logged in on their machine). If they are empty or look like a bot/Claude identity, STOP and ask the user for the correct name/email instead of guessing. Never set an Anthropic or Claude email.
3. **Never embed credentials anywhere.** No tokens, passwords, or API keys in:
   - Commit messages or branch names
   - Remote URLs (`https://user:token@github.com/...` is forbidden — use the user's existing authenticated remote / credential helper / SSH key)
   - Committed files (see Secrets section below)
4. **Push using the user's existing authentication.** The user's machine is already logged in to GitHub (credential manager or SSH). Just `git push` — do not configure new credentials, do not create PATs, do not run `gh auth login`.
5. **Commit messages**: short imperative subject line (max ~72 chars), optional body explaining *why*. Example: `Fix N+1 query in InvoiceController@index`.

## 2. Secrets & Environment Config

- Secrets live ONLY in `.env` (or the platform's secret manager). Never hardcode API keys, DB passwords, or tokens in source code.
- `.env` must be in `.gitignore`. Always check before the first commit:
  ```bash
  grep -q "^\.env" .gitignore || echo ".env" >> .gitignore
  ```
- Commit a `.env.example` with placeholder values instead.
- If a secret was ever committed, tell the user immediately — the secret must be rotated, not just deleted in a later commit.
- Before every push, do a quick scan: `git diff --cached` and look for keys/passwords/tokens.

## 3. API Design

- RESTful resource routes: `GET /api/invoices`, `POST /api/invoices`, `GET /api/invoices/{id}`, `PUT/PATCH`, `DELETE`.
- Consistent JSON response shape:
  ```json
  { "success": true, "data": { ... }, "message": "..." }
  ```
  and for errors:
  ```json
  { "success": false, "message": "...", "errors": { "field": ["..."] } }
  ```
- Correct HTTP status codes: 200/201 success, 401 unauthenticated, 403 forbidden, 404 not found, 422 validation error, 500 server error.
- Version the API when it's consumed by mobile apps (`/api/v1/...`) so old app versions don't break.
- Paginate list endpoints by default (Laravel: `->paginate(15)`), never return unbounded collections.

## 4. Validation & Security

- **Validate all input at the boundary.** Laravel: use Form Request classes (`php artisan make:request StoreInvoiceRequest`), not inline `$request->validate()` for anything non-trivial.
- **Never trust client data** — including hidden fields, IDs, and prices. Recompute prices/totals server-side.
- **SQL injection**: use the ORM/query builder with bindings. Never concatenate user input into raw queries. If raw SQL is unavoidable, use parameter bindings.
- **Mass assignment**: define `$fillable` on Eloquent models; never use `$guarded = []` in production code.
- **Auth**: use the framework's built-in auth (Laravel Sanctum for SPA/mobile tokens). Hash passwords with bcrypt/argon (`Hash::make`), never store plaintext or MD5/SHA1.
- **Authorization**: check ownership on every resource access (Policies/Gates). `Invoice::findOrFail($id)` alone is not enough — confirm the invoice belongs to the authenticated user.
- Rate-limit auth and public endpoints (Laravel: `throttle` middleware).
- Escape output where relevant; return data, not rendered HTML, from APIs.

## 5. Database & Migrations

- All schema changes go through migrations — never edit the DB by hand for tracked projects.
- Migrations must be reversible (`down()` defined) where practical.
- Add indexes for columns used in `WHERE`/`JOIN`/`ORDER BY` (foreign keys, lookup fields).
- Use foreign key constraints with explicit `onDelete` behavior.
- Watch for N+1 queries: use eager loading (`with()`) whenever iterating relations.
- SQLite-specific (common in this user's mobile-backed projects):
  - Remember SQLite has limited `ALTER TABLE` — plan column changes as new-table-copy migrations when needed.
  - Enable foreign keys explicitly if using raw SQLite (`PRAGMA foreign_keys = ON`).
- Never run destructive commands (`migrate:fresh`, `DROP`) on anything that might be production data without explicit user confirmation.

## 6. Error Handling & Logging

- Fail loudly in development, gracefully in production: never leak stack traces, SQL, or file paths to API consumers (`APP_DEBUG=false` in production).
- Catch specific exceptions, not blanket `catch (\Exception $e)` that swallows errors silently.
- Log with context (`Log::error('Payment failed', ['order_id' => $id, 'error' => $e->getMessage()])`).
- Return actionable validation errors to the client (422 with field-level messages).

## 7. Code Structure

- Thin controllers: validation in Form Requests, business logic in Service classes or Actions, data access in Models/Repositories.
- One responsibility per class/function. If a controller method exceeds ~30 lines, extract.
- Follow framework conventions (PSR-12 for PHP, standard Laravel directory structure) so the codebase stays predictable.
- Name things by domain meaning (`calculateOverdueBalance()`), not implementation (`processData2()`).

## 8. Testing & Pre-Push Checklist

Before every push, run through:

1. [ ] Code runs locally without errors (`php artisan serve` / relevant dev server)
2. [ ] Tests pass if the project has them (`php artisan test` / `npm test` / `pytest`)
3. [ ] No secrets in the diff (`git diff --cached`)
4. [ ] `.env` is not staged (`git status`)
5. [ ] `git config user.name` / `user.email` = the user's own GitHub identity
6. [ ] Commit message has NO Claude attribution or Co-Authored-By trailer
7. [ ] Migration files included if schema changed

Then commit and push using the user's existing GitHub login — nothing else.
