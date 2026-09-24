const { classifyPage } = require('../pageClassifier');

describe('pageClassifier', () => {
  test('classifies /about page', () => {
    expect(classifyPage('https://example.com/about')).toBe('about');
  });

  test('classifies /services page', () => {
    expect(classifyPage('https://example.com/services')).toBe('services');
  });

  test('classifies /products page', () => {
    expect(classifyPage('https://example.com/products')).toBe('products');
  });

  test('classifies /contact page', () => {
    expect(classifyPage('https://example.com/contact')).toBe('contact');
  });

  test('classifies /team page', () => {
    expect(classifyPage('https://example.com/team')).toBe('leadership');
  });

  test('classifies /careers page', () => {
    expect(classifyPage('https://example.com/careers')).toBe('careers');
  });

  test('classifies /case-studies page', () => {
    expect(classifyPage('https://example.com/case-studies')).toBe('case-study');
  });

  test('classifies /blog page', () => {
    expect(classifyPage('https://example.com/blog')).toBe('blog');
  });

  test('classifies /pricing page', () => {
    expect(classifyPage('https://example.com/pricing')).toBe('pricing');
  });

  test('classifies unknown page as other', () => {
    expect(classifyPage('https://example.com/random-page')).toBe('other');
  });

  test('classifies by title when URL is ambiguous', () => {
    expect(classifyPage('https://example.com/page', 'Our Services')).toBe('services');
  });

  test('classifies /solutions as services', () => {
    expect(classifyPage('https://example.com/solutions')).toBe('services');
  });

  test('classifies /leadership as leadership', () => {
    expect(classifyPage('https://example.com/leadership')).toBe('leadership');
  });
});
