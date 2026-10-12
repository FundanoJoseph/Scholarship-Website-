# Supabase, FastAPI, and Vercel Migration

## Architecture

- FastAPI owns registration, password verification, roles, authorization, and business rules. Passwords are hashed with Argon2id before they are stored.
- The browser calls FastAPI only. Public Supabase tables have RLS enabled with no browser policies; the backend uses the service-role key.
- The session JWT is an HttpOnly, Secure-in-production, SameSite=Lax cookie with an eight-hour expiry. It is sent automatically with API requests and is not kept in browser storage.
- Vercel serves the static frontend and FastAPI as two services in one Vercel project. `/api/*` is rewritten to FastAPI, so the browser uses same-origin requests.
- FastAPI authorizes document operations and creates signed Supabase Storage URLs. Uploads/downloads go directly between the browser and the private bucket; the backend does not write upload files to disk.

## 1. Create the Supabase schema

1. Create a Supabase project.
2. Open **SQL Editor** and create a new query.
3. Paste the complete contents of [`supabase/schema.sql`](supabase/schema.sql) and run it.
4. Confirm that the tables exist under `public` and that the private `scholarship-documents` bucket exists under Storage.

The schema seeds `1st Trimester, AY 2026–2027`. It includes `deleted_at` on soft-deletable records. Active backend queries filter `deleted_at IS NULL`; application status history remains append-only and is queried without a deleted-row filter.

The application form now records the student's GWA, lowest grade, and whether any failing, INC, or dropped mark exists. The backend checks the thresholds in the request before submission. Uploaded grades are still reviewed by staff; the system does not extract or verify grades from a PDF/image automatically.

## 2. Configure FastAPI locally

1. Copy `.env.example` to `.env`.
2. Set `SUPABASE_URL` to the Supabase project URL.
3. Set `SUPABASE_SERVICE_ROLE_KEY` to the Supabase service-role secret. Never put it in frontend JavaScript or a `VITE_`/public environment variable.
4. Generate `JWT_SECRET` with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
5. Set `FRONTEND_ORIGIN=http://localhost:3000` for local Vercel development.
6. Install the Python dependencies with `python -m pip install -r requirements.txt` in a virtual environment.
7. Install/link the Vercel CLI if needed and run `vercel dev` from the repository root. The Vercel rewrite serves the frontend and API from the same local origin; the browser code uses relative `/api` URLs by default.

The frontend API base is configurable through `window.SCHOLARSHIP_API_BASE_URL` or a `meta[name="scholarship-api-base-url"]` value. Leave it unset for the same-origin Vercel/local setup.

## 3. Deploy to Vercel

1. Import `FundanoJoseph/Scholarship-Website-` into Vercel and set the project root to the repository root.
2. Keep the checked-in `vercel.json`: it defines a static `frontend` service rooted at `PU scholarship system/`, a Python `backend` service using `backend.main:app`, and the `/api/*` rewrite.
3. No frontend build command is needed; the frontend is static HTML/CSS/JS. Vercel installs the backend packages from the root `requirements.txt` and uses `.python-version`.
4. In Vercel Environment Variables, set these for the backend service and for each environment you deploy:
   - `SUPABASE_URL`: the Supabase project URL.
   - `SUPABASE_SERVICE_ROLE_KEY`: the Supabase service-role secret.
   - `JWT_SECRET`: a fresh random value from `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
   - `FRONTEND_ORIGIN`: the exact deployed origin, for example `https://your-project.vercel.app` (no trailing slash). Set it to the custom domain if you use one.
   - `ENVIRONMENT=production` is optional; Vercel also enables Secure cookies through its runtime environment.
5. Do not expose the Supabase service-role key or JWT secret as frontend/build variables. They are read only by FastAPI.
6. Deploy. Verify `https://your-project.vercel.app/` loads and `https://your-project.vercel.app/api/health` returns `{"ok":true}`. Then register a test student, sign in, submit an eligible application, and verify a document can be opened by the student and staff account.

For local static development outside `vercel dev`, keep the API base same-origin and use a local reverse proxy for `/api`; do not make browser code call `localhost` to reach a separate backend.

## 4. First Admin

Recommended first-admin flow:

1. Open `https://your-project.vercel.app/register.html` and register the first account with your university email.
2. In Supabase **SQL Editor**, replace the email below with that exact email and run:

```sql
update public.users
set role = 'admin'
where lower(email) = lower('you@panpacificu.edu.ph')
  and deleted_at is null
returning id, email, role;
```

3. Confirm the returned row says `admin`, then refresh the site or sign out and sign back in. The backend reads the current role from the database on each request.
4. The account should now see the Admin-only Account Management page.

The alternative seed command is `python scripts/seed_admin.py --email you@panpacificu.edu.ph --name "Your Name"`. It prompts for the password without echoing it and refuses to run if an active Admin already exists.

## 5. Notes

- On the first API call in each browser, the frontend removes `sams_db_v3`, `sams_session_v2` (the old session user ID), `sams_reset_email`, and the `sams_files_v2` IndexedDB database. This is cleanup, not an import; export any browser-only data you need before opening the migrated site.
- Public self-service password reset is intentionally disabled until an email delivery provider is configured. The previous browser-only reset could change a password without verifying email ownership. An Admin can set a new password from Account Management, and signed-in users can change their own password.
- Documents remain private. Signed upload URLs are one-use Supabase tokens that Supabase accepts for up to two hours; signed download URLs expire after 60 seconds.
