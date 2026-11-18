const { describe, it } = require('node:test');
const assert = require('node:assert');
const { BUNDLE, makeWindow, assertNoSubmit } = require('./apply_harness');

// The report comes from another JS realm. Copy it so deepStrictEqual works.
const plain = (v) => JSON.parse(JSON.stringify(v));

function fill(fixture, url, system) {
  const ctx = makeWindow(fixture, url, [`apply/${system}.js`]);
  const report = plain(ctx.win.ApplyFill.fillForm(ctx.doc, BUNDLE, ctx.win.ApplyMaps[system]));
  return { ...ctx, report };
}

const val = (doc, sel) => doc.querySelector(sel).value;
const fileName = (doc, sel) => (doc.querySelector(sel).files[0] || {}).name;

// A protected control is never changed and never fires an input or change event.
function assertUntouched(ctx, selector) {
  const nodes = Array.from(ctx.doc.querySelectorAll(selector));
  assert.ok(nodes.length > 0, `fixture has ${selector}`);
  for (const el of nodes) {
    assert.ok(!ctx.spy.fieldEvents.includes(el), `no event on ${selector}`);
    assert.ok(!el.checked, `${selector} not checked`);
    assert.strictEqual(el.value === '' || el.type === 'radio' || el.type === 'checkbox' || el.tagName === 'SELECT', true);
  }
}

describe('Greenhouse form', () => {
  const ctx = fill('greenhouse_form.html', 'https://job-boards.greenhouse.io/example/jobs/1', 'greenhouse');
  const { doc, report } = ctx;

  it('fills the standard fields and attaches the files', () => {
    assert.strictEqual(val(doc, '#first_name'), 'Ada');
    assert.strictEqual(val(doc, '#last_name'), 'Lovelace');
    assert.strictEqual(val(doc, '#email'), 'ada@example.com');
    assert.strictEqual(val(doc, '#phone'), '555-0100');
    assert.strictEqual(val(doc, '#candidate-location'), 'Somewhere, MI');
    assert.strictEqual(fileName(doc, '#resume'), 'Resume.pdf');
    assert.strictEqual(fileName(doc, '#cover_letter'), 'CoverLetter.pdf');
    assert.deepStrictEqual(report.attached, ['resume', 'cover_letter']);
    for (const key of ['first_name', 'last_name', 'email', 'phone']) assert.ok(report.filled.includes(key), key);
    assert.ok(report.filled.some((k) => k.startsWith('location')));
  });

  it('fills the LinkedIn question by label and leaves unrelated questions empty', () => {
    const li = Array.from(doc.querySelectorAll('input')).find((i) => i.getAttribute('aria-label') === 'LinkedIn Profile');
    assert.strictEqual(li.value, 'https://linkedin.com/in/ada');
    const website = Array.from(doc.querySelectorAll('input')).find((i) => i.getAttribute('aria-label') === 'Website');
    assert.strictEqual(website.value, '');
  });

  it('lists protected questions for the human and does not touch them', () => {
    const left = report.left_for_you.join(' | ').toLowerCase();
    for (const word of ['authorized to work', 'gender', 'race', 'veteran', 'disability']) {
      assert.ok(left.includes(word), `left_for_you names ${word}`);
    }
    const protectedInputs = Array.from(doc.querySelectorAll('input')).filter((el) => {
      const ref = (el.getAttribute('aria-labelledby') || '').split(' ')[0];
      const label = doc.getElementById(ref);
      return label && /authorized to work|gender|race|veteran|disability/i.test(label.textContent);
    });
    assert.ok(protectedInputs.length >= 4, 'fixture has protected inputs');
    for (const el of protectedInputs) {
      assert.strictEqual(el.value, '');
      assert.ok(!ctx.spy.fieldEvents.includes(el));
    }
  });

  it('reports required questions that are still empty', () => {
    assert.ok(report.unfilled_required.length > 0);
    assert.ok(!report.unfilled_required.some((t) => /first name|^email$/i.test(t)));
  });

  it('never submits', () => assertNoSubmit(assert, ctx.spy));
});

describe('Lever form', () => {
  const ctx = fill('lever_form.html', 'https://jobs.lever.co/acme/1/apply', 'lever');
  const { doc, report } = ctx;

  it('fills the standard fields and attaches the resume', () => {
    assert.strictEqual(val(doc, 'input[name="name"]'), 'Ada Lovelace');
    assert.strictEqual(val(doc, 'input[name="email"]'), 'ada@example.com');
    assert.strictEqual(val(doc, 'input[name="phone"]'), '555-0100');
    assert.strictEqual(val(doc, 'input[name="location"]'), 'Somewhere, MI');
    assert.strictEqual(val(doc, 'input[name="urls[LinkedIn]"]'), 'https://linkedin.com/in/ada');
    assert.strictEqual(val(doc, 'input[name="urls[GitHub]"]'), 'https://github.com/ada');
    assert.strictEqual(fileName(doc, 'input[name="resume"]'), 'Resume.pdf');
    assert.deepStrictEqual(report.attached, ['resume']);
  });

  it('puts the cover letter text in the comments box when there is no cover letter file field', () => {
    assert.strictEqual(val(doc, 'textarea[name="comments"]'), BUNDLE.cover_letter_text);
    assert.ok(report.filled.includes('cover_letter (text)'));
  });

  it('leaves the employer field and other questions empty', () => {
    assert.strictEqual(val(doc, 'input[name="org"]'), '');
    assert.strictEqual(val(doc, 'input[name="urls[Portfolio]"]'), '');
  });

  it('lists work authorization and sponsorship for the human and does not touch the radios', () => {
    const left = report.left_for_you.join(' | ').toLowerCase();
    assert.ok(left.includes('authorized to work'));
    assert.ok(left.includes('sponsorship'));
    const radios = Array.from(doc.querySelectorAll('input[type="radio"]'));
    assert.ok(radios.length > 0);
    for (const r of radios) {
      assert.strictEqual(r.checked, false);
      assert.ok(!ctx.spy.fieldEvents.includes(r));
    }
  });

  it('never submits', () => assertNoSubmit(assert, ctx.spy));
});

describe('Ashby form', () => {
  const ctx = fill('ashby_form.html', 'https://jobs.ashbyhq.com/acme/1/application', 'ashby');
  const { doc, report } = ctx;

  it('fills the standard fields and attaches the resume and cover letter', () => {
    assert.strictEqual(val(doc, '#_systemfield_name'), 'Ada Lovelace');
    assert.strictEqual(val(doc, '#_systemfield_email'), 'ada@example.com');
    assert.strictEqual(val(doc, '#li-path'), 'https://linkedin.com/in/ada');
    assert.strictEqual(val(doc, '#gh-path'), 'https://github.com/ada');
    assert.strictEqual(val(doc, '#_systemfield_location'), 'Somewhere, MI');
    assert.strictEqual(fileName(doc, '#_systemfield_resume'), 'Resume.pdf');
    assert.strictEqual(fileName(doc, '#cl-file'), 'CoverLetter.pdf');
    assert.deepStrictEqual(report.attached, ['resume', 'cover_letter']);
  });

  it('leaves free-text questions empty and lists unfilled required ones', () => {
    assert.strictEqual(val(doc, '#lt-1'), '');
    assert.ok(report.unfilled_required.some((t) => /proud of/i.test(t)));
  });

  it('lists the sponsorship question for the human and does not touch it', () => {
    assert.ok(report.left_for_you.some((t) => /sponsorship/i.test(t)));
    assertUntouched(ctx, 'input[type="radio"]');
    assert.ok(!report.unfilled_required.some((t) => /sponsorship/i.test(t)));
  });

  it('never submits', () => assertNoSubmit(assert, ctx.spy));
});

describe('protected field matching', () => {
  const protectedLabels = [
    'Are you legally authorized to work in the United States?', 'Will you require visa sponsorship?',
    'Citizenship', 'Gender', 'Race and Ethnicity', 'Veteran Status', 'Disability Status',
    'Preferred pronouns', 'I certify that the above is true', 'I attest that I have read the policy',
  ];
  const { win } = makeWindow(null, 'https://jobs.lever.co/x', ['apply/lever.js']);
  for (const label of protectedLabels) {
    it(`protects: ${label}`, () => assert.ok(win.ApplyFill.isProtectedText(label)));
  }
  for (const label of ['First name', 'Email', 'LinkedIn Profile', 'Website', 'Trace of past work']) {
    it(`does not protect: ${label}`, () => assert.ok(!win.ApplyFill.isProtectedText(label)));
  }
});

describe('a protected control is not filled even when a field map selector matches it', () => {
  it('skips a phone-named field that mentions sponsorship', () => {
    const ctx = makeWindow(null, 'https://jobs.lever.co/x', ['apply/lever.js']);
    ctx.doc.body.innerHTML = '<form><label>Do you need sponsorship? <input name="phone"></label></form>';
    const report = plain(ctx.win.ApplyFill.fillForm(ctx.doc, BUNDLE, ctx.win.ApplyMaps.lever));
    assert.strictEqual(ctx.doc.querySelector('input').value, '');
    assert.deepStrictEqual(report.filled, []);
    assert.strictEqual(report.left_for_you.length, 1);
  });
});
