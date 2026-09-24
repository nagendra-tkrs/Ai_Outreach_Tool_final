const { extractContent } = require('../contentExtractor');

describe('contentExtractor', () => {
  test('extracts title', () => {
    const html = '<html><head><title>Test Page</title></head><body></body></html>';
    const result = extractContent(html, 'https://example.com');
    expect(result.title).toBe('Test Page');
  });

  test('extracts meta description', () => {
    const html = '<html><head><meta name="description" content="A test page"></head><body></body></html>';
    const result = extractContent(html, 'https://example.com');
    expect(result.metaDescription).toBe('A test page');
  });

  test('extracts headings', () => {
    const html = '<html><body><h1>Main Title</h1><h2>Sub Title</h2><h3>Detail</h3></body></html>';
    const result = extractContent(html, 'https://example.com');
    expect(result.headings).toEqual([
      { level: 1, text: 'Main Title' },
      { level: 2, text: 'Sub Title' },
      { level: 3, text: 'Detail' }
    ]);
  });

  test('extracts body text content', () => {
    const html = '<html><body><p>Hello world this is content.</p></body></html>';
    const result = extractContent(html, 'https://example.com');
    expect(result.content).toContain('Hello world this is content');
  });

  test('removes script and style tags', () => {
    const html = '<html><head><script>var x=1;</script><style>.a{color:red;}</style></head><body><p>Content only</p></body></html>';
    const result = extractContent(html, 'https://example.com');
    expect(result.content).not.toContain('var x');
    expect(result.content).not.toContain('color:red');
    expect(result.content).toContain('Content only');
  });

  test('counts words', () => {
    const html = '<html><body><p>one two three four five</p></body></html>';
    const result = extractContent(html, 'https://example.com');
    expect(result.wordCount).toBe(5);
  });

  test('prefers main content area', () => {
    const html = '<html><body><nav>Navigation</nav><main><p>Main content here</p></main><footer>Footer</footer></body></html>';
    const result = extractContent(html, 'https://example.com');
    expect(result.content).toContain('Main content here');
  });

  test('extracts og:title when available', () => {
    const html = '<html><head><meta property="og:title" content="OG Title"><title>Regular Title</title></head><body></body></html>';
    const result = extractContent(html, 'https://example.com');
    expect(result.title).toBe('OG Title');
  });

  test('handles empty HTML', () => {
    const result = extractContent('', 'https://example.com');
    expect(result.title).toBe('');
    expect(result.content).toBe('');
    expect(result.wordCount).toBe(0);
  });
});
