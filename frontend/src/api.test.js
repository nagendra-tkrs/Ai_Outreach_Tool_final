import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolveBaseUrl } from './api.js';

test('resolveBaseUrl - fallback to /api when unset or empty', () => {
  assert.equal(resolveBaseUrl(''), '/api');
  assert.equal(resolveBaseUrl('   '), '/api');
  assert.equal(resolveBaseUrl(null), '/api');
  assert.equal(resolveBaseUrl(undefined), '/api');
});

test('resolveBaseUrl - ensures /api suffix when host provided', () => {
  assert.equal(
    resolveBaseUrl('https://my-backend.onrender.com'),
    'https://my-backend.onrender.com/api'
  );
  assert.equal(
    resolveBaseUrl('https://my-backend.onrender.com/'),
    'https://my-backend.onrender.com/api'
  );
});

test('resolveBaseUrl - preserves existing /api suffix without duplication', () => {
  assert.equal(
    resolveBaseUrl('https://my-backend.onrender.com/api'),
    'https://my-backend.onrender.com/api'
  );
  assert.equal(
    resolveBaseUrl('https://my-backend.onrender.com/api/'),
    'https://my-backend.onrender.com/api'
  );
  assert.equal(resolveBaseUrl('/api'), '/api');
  assert.equal(resolveBaseUrl('/api/'), '/api');
});

test('vercel.json - SPA rewrite correctly handles frontend routes while excluding /api', async () => {
  const content = await readFile(new URL('../vercel.json', import.meta.url), 'utf-8');
  const config = JSON.parse(content);

  assert.ok(Array.isArray(config.rewrites), 'vercel.json must have rewrites array');
  const spaRewrite = config.rewrites.find((r) => r.destination === '/index.html');
  assert.ok(spaRewrite, 'Must have SPA rewrite targeting /index.html');

  // Convert source pattern to RegExp to verify routing behavior
  // Pattern: /((?!api/).*)
  const pattern = new RegExp(`^${spaRewrite.source}$`);

  // Frontend routes should match and redirect to /index.html
  assert.equal(pattern.test('/companies'), true, '/companies must rewrite to index.html');
  assert.equal(pattern.test('/companies/12345'), true, '/companies/:id must rewrite to index.html');
  assert.equal(pattern.test('/outbox'), true, '/outbox must rewrite to index.html');
  assert.equal(pattern.test('/settings'), true, '/settings must rewrite to index.html');
  assert.equal(pattern.test('/import'), true, '/import must rewrite to index.html');

  // API calls must NOT match and NOT rewrite to index.html
  assert.equal(pattern.test('/api/health'), false, '/api/health must not rewrite to index.html');
  assert.equal(pattern.test('/api/companies'), false, '/api/companies must not rewrite to index.html');
  assert.equal(pattern.test('/api/outreach/all'), false, '/api/outreach/all must not rewrite to index.html');
});

test('session token storage - getAuthToken, setAuthToken, clearAuthToken, isAuthenticated', async () => {
  const { getAuthToken, setAuthToken, clearAuthToken, isAuthenticated, AUTH_TOKEN_STORAGE_KEY } = await import('./api.js');

  // In Node environment without window.sessionStorage, behaves safely
  assert.equal(getAuthToken(), null);
  assert.equal(isAuthenticated(), false);

  // Mock sessionStorage on globalThis.window
  const mockStorage = new Map();
  globalThis.window = {
    sessionStorage: {
      getItem: (key) => mockStorage.get(key) || null,
      setItem: (key, val) => mockStorage.set(key, String(val)),
      removeItem: (key) => mockStorage.delete(key),
    },
  };

  try {
    assert.equal(getAuthToken(), null);
    assert.equal(isAuthenticated(), false);

    setAuthToken('test-jwt-token-12345');
    assert.equal(getAuthToken(), 'test-jwt-token-12345');
    assert.equal(isAuthenticated(), true);
    assert.equal(mockStorage.get(AUTH_TOKEN_STORAGE_KEY), 'test-jwt-token-12345');

    clearAuthToken();
    assert.equal(getAuthToken(), null);
    assert.equal(isAuthenticated(), false);
  } finally {
    delete globalThis.window;
  }
});
