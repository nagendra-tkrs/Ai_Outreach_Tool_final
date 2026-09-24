const OutreachMessage = require('../models/OutreachMessage');

// 1x1 transparent GIF buffer
const TRANSPARENT_GIF = Buffer.from(
  'R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7',
  'base64'
);

/**
 * Handle Email Open Tracking Pixel
 */
const trackOpen = async (req, res) => {
  try {
    const { messageId } = req.params;
    const cleanId = messageId.replace(/\.png|\.gif/, '');

    await OutreachMessage.findByIdAndUpdate(cleanId, {
      $inc: { openCount: 1 },
      $setOnInsert: { openedAt: new Date() },
      openedAt: new Date()
    });
  } catch (err) {
    // Ignore tracking errors so email rendering never breaks
  }

  res.set({
    'Content-Type': 'image/gif',
    'Content-Length': TRANSPARENT_GIF.length,
    'Cache-Control': 'no-cache, no-store, must-revalidate, private',
    'Pragma': 'no-cache',
    'Expires': '0'
  });
  return res.end(TRANSPARENT_GIF);
};

/**
 * Handle Email Link Click Tracking & Redirection
 */
const trackClick = async (req, res) => {
  const { messageId } = req.params;
  const targetUrl = req.query.url;

  try {
    if (messageId) {
      await OutreachMessage.findByIdAndUpdate(messageId, {
        $inc: { clickCount: 1 },
        clickedAt: new Date()
      });
    }
  } catch (err) {
    // Ignore error
  }

  if (targetUrl) {
    return res.redirect(targetUrl);
  }
  return res.redirect('/');
};

module.exports = {
  trackOpen,
  trackClick
};
