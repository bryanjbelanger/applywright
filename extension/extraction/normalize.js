globalThis.ApplywrightExtension = globalThis.ApplywrightExtension || {};

globalThis.ApplywrightExtension.normalize = {
  cleanText(text) {
    if (!text) return null;
    const cleaned = text.replace(/\s+/g, ' ').trim();
    if (cleaned === '' || cleaned === 'N/A' || cleaned === '--') return null;
    return cleaned;
  },

  cleanMultilineText(text) {
    if (!text) return null;
    let cleaned = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    cleaned = cleaned.split('\n').map(line => line.replace(/[ \t]+$/g, '')).join('\n');
    cleaned = cleaned.replace(/[ \t]+/g, ' ');
    cleaned = cleaned.replace(/\n{3,}/g, '\n\n');
    cleaned = cleaned.trim();
    if (cleaned === '') return null;
    return cleaned;
  },

  canonicalizeUrl(urlStr, baseUrl) {
    if (!urlStr) return null;
    try {
      const url = new URL(urlStr, baseUrl);
      if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
      
      url.hash = '';
      
      const trackingParams = ['utm_source', 'utm_medium', 'utm_campaign', 'ref', 'source'];
      for (const p of trackingParams) {
        url.searchParams.delete(p);
      }
      
      return url.toString();
    } catch (e) {
      return null;
    }
  }
};
