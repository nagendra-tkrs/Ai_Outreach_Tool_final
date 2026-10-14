import axios from 'axios';

/**
 * Resolves the API base URL.
 * When `VITE_API_URL` is configured (e.g. for Vercel pointing to Render), it is used.
 * Otherwise falls back to '/api' for local development with Vite proxy.
 */
export function resolveBaseUrl(envUrl) {
  if (!envUrl || typeof envUrl !== 'string' || !envUrl.trim()) {
    return '/api';
  }
  const clean = envUrl.trim().replace(/\/+$/, '');
  return clean.endsWith('/api') ? clean : `${clean}/api`;
}

const rawEnvUrl =
  (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) ||
  (typeof process !== 'undefined' && process.env?.VITE_API_URL);

export const API_BASE_URL = resolveBaseUrl(rawEnvUrl);

// Key for storing session token (sessionStorage ensures tokens are cleared on browser/tab close)
export const AUTH_TOKEN_STORAGE_KEY = 'ai_outreach_auth_token';

export function getAuthToken() {
  if (typeof window !== 'undefined' && window.sessionStorage) {
    try {
      return window.sessionStorage.getItem(AUTH_TOKEN_STORAGE_KEY);
    } catch {
      return null;
    }
  }
  return null;
}

export function setAuthToken(token) {
  if (typeof window !== 'undefined' && window.sessionStorage) {
    try {
      if (token) {
        window.sessionStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token);
      } else {
        window.sessionStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
      }
    } catch {
      // Storage unavailable or disabled
    }
  }
}

export function clearAuthToken() {
  setAuthToken(null);
}

export function isAuthenticated() {
  return Boolean(getAuthToken());
}

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120000,
});

// Request Interceptor: Attach Bearer authorization header if token exists
api.interceptors.request.use((config) => {
  const token = getAuthToken();
  if (token) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Response Interceptor: Surface backend messages and detect 401 Unauthorized
api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const status = error.response?.status;
    const data = error.response?.data;

    // Surface clear, actionable error message from backend
    const message =
      (typeof data?.detail === 'string' && data.detail) ||
      data?.message ||
      error.message ||
      'Something went wrong';

    // When 401 Unauthorized occurs, notify application components to prompt for login
    if (status === 401 && typeof window !== 'undefined') {
      clearAuthToken();
      window.dispatchEvent(
        new CustomEvent('auth:unauthorized', {
          detail: { message },
        })
      );
    }

    return Promise.reject(new Error(message));
  }
);

/**
 * Log into the single-user dashboard with owner credentials.
 */
export async function login(username, password) {
  const response = await api.post('/auth/login', { username, password });
  if (response?.token) {
    setAuthToken(response.token);
  }
  return response;
}

/**
 * Log out and clear session credentials.
 */
export async function logout() {
  try {
    await api.post('/auth/logout');
  } catch {
    // Ignore network error on logout
  } finally {
    clearAuthToken();
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('auth:logout'));
    }
  }
}

export default api;
