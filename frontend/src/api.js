import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  timeout: 120000,
});

api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const data = error.response?.data;
    // FastAPI carries the human-readable failure in `detail` (e.g. draft save
    // validation errors) — surface it so the UI shows a clear, actionable
    // message instead of "Request failed with status code 400".
    const message =
      (typeof data?.detail === 'string' && data.detail) ||
      data?.message ||
      error.message ||
      'Something went wrong';
    return Promise.reject(new Error(message));
  }
);

export default api;
