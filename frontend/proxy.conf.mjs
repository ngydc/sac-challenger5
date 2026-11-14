// Dev-server proxy: forwards /api/* to the FastAPI backend.
// Locally the backend runs on localhost:8000; in Docker, docker-compose sets API_TARGET=http://backend:8000.
const target = process.env.API_TARGET ?? 'http://localhost:8000';

export default {
  '/api': {
    target,
    secure: false,
    changeOrigin: true,
  },
};
