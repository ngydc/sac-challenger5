/**
 * Base path for all backend calls (FastAPI).
 * The dev server (proxy.conf.mjs) and nginx (nginx.conf) forward /api to the backend,
 * so the frontend never needs to know the backend's host.
 */
export const API_BASE_URL = '/api';
