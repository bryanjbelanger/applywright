const { describe, it } = require('node:test');
const assert = require('node:assert');
const { JSDOM } = require('jsdom');

// F2: Delete Flagged Jobs must act only on cards whose review link id equals a
// listed id. Id 123 must never match the card for id 1234.
function buildList(ids) {
  const cards = ids.map(id => `
    <div class="shadow-card" data-card="${id}">
      <a href="/applications/review/${id}">Job ${id}</a>
      <div class="cursor-pointer"><svg class="ic_trash"></svg></div>
    </div>`).join('');
  const dom = new JSDOM(`<html><body><div class="at-card">${cards}</div></body></html>`, {
    url: 'https://app.jobcopilot.com/'
  });
  const doc = dom.window.document;
  dom.window.HTMLElement.prototype.scrollIntoView = () => {};
  const clicked = [];
  doc.querySelectorAll('.shadow-card').forEach(card => {
    const wrap = card.querySelector('div.cursor-pointer');
    wrap.addEventListener('click', () => {
      clicked.push(card.getAttribute('data-card'));
      const btn = doc.createElement('button');
      btn.textContent = 'Confirm';
      Object.defineProperty(btn, 'offsetParent', { get: () => doc.body });
      btn.addEventListener('click', () => { card.remove(); btn.remove(); });
      doc.body.appendChild(btn);
    });
  });
  return { dom, doc, clicked };
}

function loadContent(dom) {
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  globalThis.location = dom.window.location;
  globalThis.ApplywrightExtension = {};
  globalThis.chrome = {
    runtime: { onMessage: { addListener: () => {} }, onConnect: { addListener: () => {} } },
    storage: { local: { set: async () => {} } }
  };
  delete require.cache[require.resolve('../content.js')];
  require('../content.js');
  return globalThis.ApplywrightExtension.content;
}

describe('deleteFlagged', () => {
  it('does not act on a card whose id only starts with a listed id', async () => {
    const { dom, doc, clicked } = buildList(['1234', '123']);
    const content = loadContent(dom);

    const result = await content.deleteFlagged({ postMessage: () => {} }, ['123']);

    assert.deepStrictEqual(clicked, ['123']);
    assert.deepStrictEqual(result.deleted, ['123']);
    assert.deepStrictEqual(result.failed, []);
    assert.ok(doc.querySelector('[data-card="1234"]'), 'card 1234 must remain');
  });

  it('confirms its own prompt when another job already has a confirmation open', async () => {
    const { dom, doc } = buildList(['999', '123']);
    // Job 999 already shows a confirmation that the run did not open.
    const stale = doc.createElement('button');
    stale.textContent = 'Confirm';
    Object.defineProperty(stale, 'offsetParent', { get: () => doc.body });
    stale.addEventListener('click', () => {
      doc.querySelector('[data-card="999"]').remove();
      stale.remove();
    });
    doc.body.appendChild(stale);
    const content = loadContent(dom);

    const result = await content.deleteFlagged({ postMessage: () => {} }, ['123']);

    assert.deepStrictEqual(result.deleted, ['123']);
    assert.ok(doc.querySelector('[data-card="999"]'), 'card 999 must remain');
  });
});
