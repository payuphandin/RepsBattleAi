# RepBattle AI — Deployment Preparation

## Architecture

- Frontend: Next.js, deploy from the `frontend/` directory (Vercel is a suitable option).
- Backend: FastAPI + MediaPipe + OpenCV, deploy from the `cv/` directory as a Docker Web Service (Render is a suitable option).
- The browser connects to the backend using HTTPS for REST and WSS for camera frames.

## Environment variables

### Frontend

Set this in the frontend hosting dashboard before the production build:

```env
NEXT_PUBLIC_API_URL=https://YOUR-BACKEND-DOMAIN
```

Use the backend's public HTTPS origin only. Do not add `/ws/pushup` or a trailing slash.

Next.js embeds `NEXT_PUBLIC_*` variables into the browser bundle during `next build`, so set the value before building/redeploying.

### Backend

Set these in the backend hosting dashboard:

```env
APP_ENV=production
FRONTEND_ORIGINS=https://YOUR-FRONTEND-DOMAIN
```

Use the frontend's exact origin, without a path or trailing slash. Multiple trusted frontend origins can be separated by commas.

The hosting platform supplies `PORT`. The Docker image binds Uvicorn to `0.0.0.0:$PORT` and uses port 10000 only as a local fallback.

## Suggested Vercel + Render setup

### Frontend on Vercel

1. Import the GitHub repository.
2. Set Root Directory to `frontend`.
3. Keep the framework preset as Next.js.
4. Add `NEXT_PUBLIC_API_URL` using the backend URL after the backend service exists.
5. Deploy/redeploy after setting the environment variable.

### Backend on Render

1. Create a Web Service from the same GitHub repository.
2. Set Root Directory to `cv`.
3. Select the Docker runtime.
4. Set Health Check Path to `/health`.
5. Add `APP_ENV=production` and `FRONTEND_ORIGINS=https://YOUR-FRONTEND-DOMAIN`.
6. Keep a single running instance while room state is stored in process memory.

Render Web Services support WebSocket connections. A free instance can spin down after 15 minutes without inbound traffic; use a paid always-on instance for dependable production sessions.

## Important current limitations

- Room state is held in a Python dictionary in process memory. Rooms and scores are lost when the backend restarts or redeploys.
- Do not run multiple backend instances yet. Different instances would have different room dictionaries, so players could be routed to different copies of the room.
- Before public production use or horizontal scaling, move room/session state to a shared store (for example Redis) and add appropriate access control, rate limits, and abuse protection.
- The existing `requirements.txt` does not pin package versions. Create a tested lock/constraints file from the working Python environment before treating the Docker build as reproducible.
- The Pose Landmarker model must be committed at `cv/models/pose_landmarker_lite.task`; the Docker build copies the `cv/` directory into the image.

## Pre-deploy checks

From the repository root:

```powershell
git status
```

Backend tests (from `cv/`):

```powershell
py -m unittest discover -s tests -v
```

Frontend checks (from `frontend/`):

```powershell
npm run lint
npx tsc --noEmit
npm run build
```

For a container smoke test, use Docker Desktop and build from the `cv/` directory:

```powershell
docker build -t repbattle-api .
docker run --rm -p 10000:10000 -e PORT=10000 -e APP_ENV=production -e FRONTEND_ORIGINS=http://localhost:3000 repbattle-api
```

Then check `http://localhost:10000/health`.
