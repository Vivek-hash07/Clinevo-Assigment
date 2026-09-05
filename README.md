# Smart Inbox Assistant

Clinevo reviewer app: Angular on port 8000, FastAPI on port 8080, Neon Postgres from `backend/.env`.

Run Python locally. There is no Docker image for this project.

## Layout

```text
frontend   Angular reviewer UI
backend    FastAPI (reads backend/.env)
```

| Service | URL |
|---|---|
| Angular | http://localhost:8000 |
| FastAPI | http://localhost:8080 |
| Health | http://localhost:8080/api/health |
| After login | http://localhost:8000/inbox |

Open the app at **http://localhost:8000**, not `127.0.0.1`.

## Environment

The API reads a repo-root `.env` when present and then **`backend/.env`** (backend values take
precedence). Copy `backend/.env.example` if you need a fresh file. **Never commit either `.env`.**

Required: `DATABASE_URL`, `JWT_SECRET`, `TOKEN_ENCRYPTION_KEY`. SMTP values match Amazon Mail Manager (region `ap-south-1`).

## Google Cloud — any Google account can sign in

Continue with Google only asks for **openid, email, profile**. That is enough for any Google account once the consent screen is **published**.

1. Google Cloud → **APIs & Services** → **OAuth consent screen**
2. User type **External**
3. Click **Publish app** (status **In production**). Confirm the warning. You do **not** need Google’s brand verification for sign-in.
4. Keep the same Web client origins and redirect URI below.

If status stays **Testing**, Google will only allow emails you add as testers. Publishing is what opens it to every Google account.

**Gmail mailbox sync** uses the restricted `gmail.readonly` scope. Google will still block that for the public until you complete Gmail API verification. Sign-in does not wait on that. Use **Sync my mail** after login when you are ready to request mailbox access.

**Authorized JavaScript origins** (this is the origin)

```text
http://localhost:8000
```

**Authorized redirect URIs** (this is the callback / fallback)

```text
http://localhost:8080/api/auth/google/callback
```

Paste the client ID and secret into `backend/.env`:

```env
GOOGLE_CLIENT_ID=....apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=....
GOOGLE_REDIRECT_URI=http://localhost:8080/api/auth/google/callback
```

Restart FastAPI after saving.

## Run

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --reload-dir app --port 8080 --host 0.0.0.0
```

```bash
cd frontend
npm install
npm start
```

Tables are created on API startup.

## Auth

- `/sign-up` and `/sign-in` — email/password or Continue with Google
- `/forgot-password` — SMTP reset email with a random, hashed, 30-minute token
- `/reset-password` — one-time link; requesting another link invalidates earlier links
- Access cookies are signed and short lived; refresh tokens are hashed, rotated, and revocable
- Password reset revokes all previous sessions
- After login you land on `/inbox`

For production, serve the Angular build and `/api` from the same HTTPS origin. Set
`APP_ENV=production`, HTTPS `FRONTEND_URL`/`BACKEND_URL`, and `COOKIE_SECURE=true`. The backend
refuses unsafe production settings.
