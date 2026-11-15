# Frontend

Angular 22 app (standalone components, SCSS, Vitest). Setup and Docker commands are in the [root README](../README.md); the backend API it calls is described in [docs/API.md](../docs/API.md).

- `npm start`: dev server on http://localhost:4200, `/api` is proxied to the backend (`proxy.conf.mjs`)
- `npm run build`: production build into `dist/` (served by nginx in Docker, see `nginx.conf`)
- `npm test`: unit tests (Vitest)
