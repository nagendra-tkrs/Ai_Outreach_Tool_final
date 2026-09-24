const { extractLinks } = require('../linkExtractor');

describe('linkExtractor', () => {
  test('extracts internal links', () => {
    const html = '<a href="/about">About</a><a href="/contact">Contact</a>';
    const links = extractLinks(html, 'https://example.com');
    expect(links.length).toBe(2);
    expect(links.some(l => l.includes('/about'))).toBe(true);
    expect(links.some(l => l.includes('/contact'))).toBe(true);
  });

  test('excludes external links', () => {
    const html = '<a href="/about">About</a><a href="https://other.com">Other</a>';
    const links = extractLinks(html, 'https://example.com');
    expect(links.length).toBe(1);
  });

  test('excludes anchors', () => {
    const html = '<a href="#section">Section</a><a href="/about">About</a>';
    const links = extractLinks(html, 'https://example.com');
    expect(links.length).toBe(1);
  });

  test('excludes mailto links', () => {
    const html = '<a href="mailto:test@example.com">Email</a><a href="/about">About</a>';
    const links = extractLinks(html, 'https://example.com');
    expect(links.length).toBe(1);
  });

  test('excludes javascript links', () => {
    const html = '<a href="javascript:void(0)">Click</a><a href="/about">About</a>';
    const links = extractLinks(html, 'https://example.com');
    expect(links.length).toBe(1);
  });

  test('deduplicates links', () => {
    const html = '<a href="/about">A</a><a href="/about/">B</a>';
    const links = extractLinks(html, 'https://example.com');
    expect(links.length).toBe(1);
  });

  test('handles empty HTML', () => {
    const links = extractLinks('', 'https://example.com');
    expect(links).toEqual([]);
  });
});
