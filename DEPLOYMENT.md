# AI Finder — deployment guide

## Supabase
1. Create a Supabase project.
2. Run `supabase/schema.sql` in the SQL Editor.
3. Copy the project URL, public anon key, and service-role key.
4. Keep the service-role key only in backend environment variables. Never put it in browser JavaScript.

## Frontend
Edit `config.js`:
- `API_BASE_URL`: deployed FastAPI URL, without a trailing slash.
- `SUPABASE_URL`: Supabase project URL.
- `SUPABASE_ANON_KEY`: public anon key only.

## Backend
Deploy the `backend` directory using its Dockerfile, or run:

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

Set these environment variables in the backend host:
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `OPENROUTER_API_KEY`
- `OPENROUTER_MODEL` (optional; default `openai/gpt-4o-mini`)
- `IMAGE_API_BASE`
- `IMAGE_API_KEY`
- `IMAGE_MODEL`
- `ALLOWED_ORIGINS` (production website origin)

Use `backend/.env.example` as the variable checklist. Do not commit real `.env` files or provider keys.

## GitHub Pages
Enable GitHub Pages under Settings → Pages and select GitHub Actions. The workflow deploys the static frontend after commits to `main`.

## Verify
Open `/health` and `/docs` on the deployed backend. The health response should report AI and database configuration as enabled.

## Important
GitHub Pages hosts only the static frontend. Real AI requests and private messages require a deployed backend, a configured Supabase project, and valid provider credentials. Add rate limits, usage quotas, privacy terms, email verification, blocking and reporting before public launch. Replace wildcard CORS with the exact production frontend origin.