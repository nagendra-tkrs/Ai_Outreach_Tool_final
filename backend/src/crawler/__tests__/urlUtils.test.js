const { normalizeUrl, extractDomain, isSameDomain, resolveUrl, filterSameDomainLinks, urlsAreEqual } = require('../urlUtils');

describe('urlUtils', () => {
  describe('normalizeUrl', () => {
    test('normalizes https URL', () => {
      expect(normalizeUrl('https://Example.COM/')).toBe('https://example.com/');
    });

    test('removes trailing slash from non-root paths', () => {
      expect(normalizeUrl('https://example.com/about/')).toBe('https://example.com/about');
    });

    test('preserves root slash', () => {
      expect(normalizeUrl('https://example.com/')).toBe('https://example.com/');
    });

    test('removes fragment', () => {
      expect(normalizeUrl('https://example.com/page#section')).toBe('https://example.com/page');
    });

    test('preserves search params sorted', () => {
      expect(normalizeUrl('https://example.com/page?b=2&a=1')).toBe('https://example.com/page?a=1&b=2');
    });

    test('handles empty string', () => {
      expect(normalizeUrl('')).toBe('');
    });

    test('handles null', () => {
      expect(normalizeUrl(null)).toBe('');
    });

    test('preserves path', () => {
      expect(normalizeUrl('https://example.com/about')).toBe('https://example.com/about');
    });

    test('handles www prefix', () => {
      expect(normalizeUrl('https://www.example.com')).toBe('https://www.example.com/');
    });
  });

  describe('extractDomain', () => {
    test('extracts domain without www', () => {
      expect(extractDomain('https://www.example.com')).toBe('example.com');
    });

    test('extracts domain with www', () => {
      expect(extractDomain('https://example.com')).toBe('example.com');
    });

    test('extracts domain with path', () => {
      expect(extractDomain('https://example.com/about')).toBe('example.com');
    });

    test('returns empty for invalid URL', () => {
      expect(extractDomain('not-a-url')).toBe('');
    });
  });

  describe('isSameDomain', () => {
    test('same domain matches', () => {
      expect(isSameDomain('https://example.com/page', 'example.com')).toBe(true);
    });

    test('www subdomain matches', () => {
      expect(isSameDomain('https://www.example.com/page', 'example.com')).toBe(true);
    });

    test('different domain does not match', () => {
      expect(isSameDomain('https://other.com/page', 'example.com')).toBe(false);
    });

    test('deep subdomain matches', () => {
      expect(isSameDomain('https://blog.example.com/page', 'example.com')).toBe(true);
    });
  });

  describe('resolveUrl', () => {
    test('resolves relative URL', () => {
      expect(resolveUrl('https://example.com/', '/about')).toBe('https://example.com/about');
    });

    test('resolves absolute URL', () => {
      expect(resolveUrl('https://example.com/', 'https://other.com')).toBe('https://other.com/');
    });

    test('returns base URL for empty relative', () => {
      expect(resolveUrl('https://example.com', '')).toBe('https://example.com/');
    });
  });

  describe('filterSameDomainLinks', () => {
    test('filters to same domain only', () => {
      const links = [
        'https://example.com/about',
        'https://other.com/page',
        'https://example.com/contact'
      ];
      const result = filterSameDomainLinks(links, 'example.com');
      expect(result).toHaveLength(2);
    });

    test('deduplicates URLs', () => {
      const links = [
        'https://example.com/about',
        'https://example.com/about/'
      ];
      const result = filterSameDomainLinks(links, 'example.com');
      expect(result).toHaveLength(1);
    });

    test('excludes static files', () => {
      const links = [
        'https://example.com/style.css',
        'https://example.com/image.png',
        'https://example.com/about'
      ];
      const result = filterSameDomainLinks(links, 'example.com');
      expect(result).toHaveLength(1);
      expect(result[0]).toContain('/about');
    });

    test('handles empty input', () => {
      expect(filterSameDomainLinks([], 'example.com')).toEqual([]);
    });
  });

  describe('urlsAreEqual', () => {
    test('equal URLs', () => {
      expect(urlsAreEqual('https://example.com/', 'https://example.com')).toBe(true);
    });

    test('different URLs', () => {
      expect(urlsAreEqual('https://example.com/a', 'https://example.com/b')).toBe(false);
    });
  });
});
