# Plan: Admin authentication (super user, admin users, token-gated Books / Review / Traces)

## Context
Books, Review and Traces are open to anyone who can reach the app (only Traces has a shared-token gate). The goal is that only a super user or an admin user can use them. Decisions made with the user:
- **Credential for API access is the existing shared `ADMIN_TOKEN`** (X-Admin-Token header). Users sign in with username and password; a successful login returns the token to the browser.
- **Super user `ai-sailors` is seeded from `.env`** (git-ignored), stored as a salted hash.
- **All admin APIs are gated server-side; `TRACE_DASHBOARD` flag stays** (Traces needs the flag *and* a sign-in).
- Play (children) stays public.

Consequence of a shared token, stated plainly: the token alone cannot say *who* is calling, and anyone who has signed in has seen it. So (1) sensitive user management re-checks the acting super user's password in the request, and (2) disabling a user only blocks future sign-ins; rotate `ADMIN_TOKEN` to cut off someone who already signed in.

## Backend

1. **Migration** `src/storyquest/stores/migrations/app/0004_admin_users.sql`: table `admin_users` (`id`, `username` UNIQUE lowercase, `password_hash`, `role` CHECK `super|admin`, `active`, `created_at`, `created_by`).
2. **Settings** (`config.py`, `config.env`, `.env.example`): add `superuser_username`, `superuser_password` (repr=False). Comments in `config.env`; placeholders only in `.env.example`.
3. **Passwords** `stores/admin_users.py` (stdlib only): `hash_password` / `verify_password` with `hashlib.scrypt`, random salt, `secrets.compare_digest`; `create_user`, `get_user`, `list_users`, `seed_superuser(conn, settings)` (create if missing; re-hash if the env password changed; always role `super`). Username rules: 3-40 chars `[a-z0-9._-]`, lowercased. Password min 10 chars.
4. **Startup**: `create_app` calls `seed_superuser` after migrating `app.db`, next to the existing `prune_traces` call.
5. **Auth module** `api/auth.py`: 
   - `require_admin(settings)` dependency: 401 if `ADMIN_TOKEN` unset or header missing/wrong (constant-time compare). Replaces the gate inside `api/traces.py` (which keeps its extra 404 when `TRACE_DASHBOARD` is off).
   - `POST /api/auth/login {username, password}` -> `{token, username, role}`. Unknown user, wrong password and disabled user all give the same 401. Fail-closed 503 if `ADMIN_TOKEN` is unset. In-memory throttle: 5 failures per username per 5 minutes -> 429.
   - `GET /api/admin/users` (token): username, role, active, created_at.
   - `POST /api/admin/users` (token + `{username, password, acting_username, acting_password}`): the acting user must be an active `super` with the right password; creates an `admin`. 409 on duplicate, 422 on weak password/bad username. Only admins are creatable; the super user comes only from `.env`.
6. **Gate everything admin** in `api/main.py` using the dependency: `POST /api/admin/books`, `GET /api/admin/books/{id}/review`, `.../approve`, `.../publish`, `GET /api/library`, `POST /api/library/{book}/chapters/{idx}/prepare`, plus the traces router and users routes. `GET /api/missions`, sessions, choice, ask, health stay public. Update the "no sign-in yet" docstring in `api/admin.py`.
7. **CLI**: implement the existing placeholder `make admin-user` -> `storyquest admin create-user` (prompts for username and password, getpass) so admins can also be created without the UI.

## Frontend (`web/src`)
- `auth.tsx`: `AuthProvider` + `useAuth()` holding `{username, role, token}` in `sessionStorage` (per tab, cleared on sign-out). `api.ts` reuses `getAdminToken`/`setAdminToken`, sends `X-Admin-Token` on every request when set, and on any 401 from a gated route clears auth and sends the user to `/login`.
- `pages/Login.tsx`: username and password form, error text, redirect back to the page that was asked for.
- `pages/AdminUsers.tsx` (super user only): list of admins plus an "Add admin" form (username, password, your password to confirm).
- `App.tsx`: Books / Review / Traces / Admins tabs render only when signed in (Admins only for `super`); a "Sign in" link when signed out and "Sign out (name)" when signed in. New `RequireAdmin` route guard wraps `/books`, `/review*`, `/traces*`, `/admins` and redirects to `/login`. Remove the token form in `components/TraceGate.tsx` (keep its "dashboard is switched off" message for the 404).
- Small CSS additions in `styles.css` following the existing `.card` / form patterns.

## Secrets handling
- Put `SUPERUSER_USERNAME=ai-sailors` and `SUPERUSER_PASSWORD=...` only in local `.env` (already git-ignored). Never in `config.env`, code, tests or docs.
- Flag to the user: `.env.example` currently contains a real-looking `ADMIN_TOKEN` value and is committed; replace it with a blank/placeholder and rotate that token. The super user password was also typed into this chat, so change it after first setup.

## Tests (`tests/api/test_auth.py` plus updates)
- Hashing: verify right/wrong password, different salts per hash.
- Seed: creates once, idempotent, re-hashes when the env password changes, absent when env unset.
- Login: success returns token and role; wrong password, unknown and disabled users give an identical 401; throttle returns 429; unset `ADMIN_TOKEN` fails closed.
- Gating: each admin/library route returns 401 without the token and works with it; public routes stay open.
- Users: list needs the token; add needs the acting super user's password; an `admin` cannot add; duplicate 409; weak password and bad username 422; a created admin can log in.
- Update existing tests (`tests/api/test_admin.py`, `test_library.py`, `test_api.py`, `test_traces.py`) to send the token header.

## Docs
Update `docs/ai-sailors-technical-doc.md` (6.2 API table, 6.3 tabs, 6.5 access, section 8 table, section 9 "no authentication" item, Appendix A settings) and mirror it in the `.docx` by surgical XML edits as before (back up first, never regenerate). Update `README` and `docs/design/06-web-app-and-api.md` where they mention admin access.

## Verification
1. `make check` (ruff, mypy strict, pytest) passes with the new tests.
2. `make dev-api` and `make dev-web` with `SUPERUSER_*`, `ADMIN_TOKEN` in `.env` and `TRACE_DASHBOARD=true`:
   - Signed out: the nav shows no Books/Review/Traces; visiting `/books`, `/review`, `/traces` redirects to `/login`; `curl localhost:8000/api/admin/traces`, `/api/library` and a publish call all return 401.
   - Sign in as `ai-sailors`: all four tabs appear; add an admin; sign out; sign in as that admin: Books/Review/Traces work, the Admins tab is hidden, and `POST /api/admin/users` with the admin's credentials returns 403/401.
   - Wrong password five times returns 429; a child quest (Play, ask a question) still works while signed out.
3. `storyquest admin create-user` creates a user who can sign in.
