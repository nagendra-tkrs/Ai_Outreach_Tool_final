const classifyPage = (url, title = '', content = '') => {
  const urlLower = url.toLowerCase();
  const titleLower = (title || '').toLowerCase();

  const rules = [
    {
      patterns: [
        /\/team/i, /\/our-team/i, /\/leadership/i, /\/management/i, /\/board/i,
        /\/people/i, /\/executives/i, /\/founders/i, /\/advisors/i, /\/staff/i,
        /\/who-we-are\/leadership/i, /\/company\/team/i, /\/about\/team/i,
        /\/about-us\/leadership/i, /\/meet-the-team/i, /\/bio\//i, /\/profile\//i
      ],
      type: 'leadership'
    },
    {
      patterns: [
        /\/about/i, /\/company/i, /\/our-story/i, /\/who-we-are/i, /\/overview/i, /\/history/i
      ],
      type: 'about'
    },
    {
      patterns: [
        /\/contact/i, /\/get-in-touch/i, /\/reach-us/i, /\/connect/i, /\/locations/i, /\/office/i
      ],
      type: 'contact'
    },
    {
      patterns: [
        /\/service/i, /\/what-we-do/i, /\/solutions/i, /\/offerings/i, /\/capabilities/i
      ],
      type: 'services'
    },
    {
      patterns: [
        /\/product/i, /\/platform/i, /\/catalog/i, /\/features/i, /\/technology/i
      ],
      type: 'products'
    },
    {
      patterns: [/\/industr/i, /\/sector/i, /\/verticals/i],
      type: 'industries'
    },
    {
      patterns: [/\/customer/i, /\/client/i, /\/partner/i, /\/ecosystem/i],
      type: 'customers'
    },
    {
      patterns: [/\/case-stud/i, /\/success-stor/i, /\/portfolio/i, /\/work\//i, /\/projects/i],
      type: 'case-study'
    },
    {
      patterns: [/\/pricing/i, /\/plan/i, /\/cost/i, /\/quote/i],
      type: 'pricing'
    },
    {
      patterns: [/\/career/i, /\/job/i, /\/hiring/i, /\/recruit/i, /\/join-us/i],
      type: 'careers'
    },
    {
      patterns: [/\/blog/i, /\/news/i, /\/article/i, /\/post/i, /\/press/i, /\/media/i],
      type: 'blog'
    },
    {
      patterns: [/\/resource/i, /\/guide/i, /\/whitepaper/i, /\/ebook/i, /\/webinar/i],
      type: 'resources'
    },
    {
      patterns: [/\/faq/i, /\/help/i, /\/support/i, /\/knowledge-base/i],
      type: 'support'
    },
    {
      patterns: [/\/privacy/i, /\/terms/i, /\/legal/i, /\/policy/i, /\/cookie/i, /\/disclaimer/i],
      type: 'legal'
    },
  ];

  for (const rule of rules) {
    if (rule.patterns.some(p => p.test(urlLower))) return rule.type;
  }

  // Title checks
  if (titleLower.includes('team') || titleLower.includes('leadership') || titleLower.includes('founder') || titleLower.includes('executive') || titleLower.includes('board of director')) return 'leadership';
  if (titleLower.includes('about') || titleLower.includes('who we are') || titleLower.includes('our story')) return 'about';
  if (titleLower.includes('contact') || titleLower.includes('get in touch') || titleLower.includes('reach out')) return 'contact';
  if (titleLower.includes('service') || titleLower.includes('solution') || titleLower.includes('what we do')) return 'services';
  if (titleLower.includes('product') || titleLower.includes('platform')) return 'products';

  return 'other';
};

/**
 * Priority scoring for crawler queue:
 * Higher number = higher priority to crawl first!
 */
const getPagePriority = (url) => {
  const urlLower = url.toLowerCase();
  // Highest priority: Leadership, Team, Founders, Executives
  if (/(leadership|team|founder|management|board|executive|people|staff|who-we-are|about-us)/i.test(urlLower)) return 100;
  // High priority: About, Contact, Story
  if (/(about|contact|connect|company|story)/i.test(urlLower)) return 80;
  // Medium priority: Services, Products, Solutions
  if (/(service|product|solution|platform|pricing)/i.test(urlLower)) return 50;
  // Low priority: Case studies, Clients
  if (/(case-stud|customer|portfolio|client)/i.test(urlLower)) return 20;
  // Lowest priority: Blogs, legal, careers
  if (/(blog|news|article|privacy|terms|legal|career|job)/i.test(urlLower)) return 5;
  return 30;
};

module.exports = { classifyPage, getPagePriority };
