const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const url = 'http://127.0.0.1:8843/bookings/zzz-test-org-riverside-academy-proposal-qa/';
  const results = [];

  // ---- Desktop pass ----
  {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    page.on('pageerror', (e) => results.push('PAGE ERROR: ' + e.message));
    page.on('console', (m) => { if (m.type() === 'error') results.push('CONSOLE ERROR: ' + m.text()); });
    await page.goto(url, { waitUntil: 'networkidle' });

    // Sample flag still present
    const sampleFlagText = await page.locator('.sample-flag').innerText();
    results.push('sample-flag text: ' + sampleFlagText.replace(/\s+/g, ' ').slice(0, 60));

    // Roadmap badge present
    const badgeCount = await page.locator('.roadmap-badge').count();
    results.push('roadmap-badge count on page: ' + badgeCount);

    // Mailto link in Next Steps section (need to navigate there)
    await page.click('.chapter-link[data-goto="sec-next"]');
    await page.waitForTimeout(200);
    const mailtoHref = await page.locator('#sec-next .cta-fine a').getAttribute('href');
    results.push('Next Steps "prefer email" href: ' + mailtoHref);

    // CTA two-step confirm flow
    const readyBtn = page.locator('#sec-next .btn-primary', { hasText: 'Ready to Move Forward' });
    await readyBtn.click();
    await page.waitForTimeout(150);
    const confirmHeadline = await page.locator('#sec-next .cta-module h3').innerText();
    results.push('After first click, headline: ' + confirmHeadline);
    const stillPending = await page.locator('#sec-next .cta-module').innerText();
    results.push('Confirm step shows "Yes, we\'re ready": ' + stillPending.includes("Yes, we're ready"));
    await page.click('#sec-next .cta-module .btn-primary');
    await page.waitForTimeout(150);
    const finalHeadline = await page.locator('#sec-next .cta-module h3').innerText();
    results.push('After confirm click, final headline: ' + finalHeadline);

    await page.screenshot({ path: '/tmp/qa_desktop_next.png', fullPage: false });
    await page.close();
  }

  // ---- Fresh page: change-request form validation ----
  {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    await page.goto(url, { waitUntil: 'networkidle' });
    await page.click('.chapter-link[data-goto="sec-overview"]');
    await page.waitForTimeout(150);
    await page.click('#sec-overview .cta-secondary-link');
    await page.waitForTimeout(150);
    const sendBtn = page.locator('#sec-overview .cta-module .btn-primary');
    const disabledEmpty = await sendBtn.isDisabled();
    results.push('Send Request disabled when textarea empty: ' + disabledEmpty);
    const labelText = await page.locator('#sec-overview .cta-textarea-label').innerText();
    results.push('Textarea label text: ' + labelText);
    await page.fill('#sec-overview .cta-textarea', 'Please move our arrival a day later.');
    await page.waitForTimeout(100);
    const disabledAfterTyping = await sendBtn.isDisabled();
    results.push('Send Request disabled after typing: ' + disabledAfterTyping);
    const responseNote = await page.locator('#sec-overview .cta-fine').last().innerText();
    results.push('Response-time note shown: ' + responseNote);
    await page.close();
  }

  // ---- Pricing section copy ----
  {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    await page.goto(url, { waitUntil: 'networkidle' });
    await page.click('.chapter-link[data-goto="sec-pricing"]');
    await page.waitForTimeout(200);
    const conditions = await page.locator('#sec-pricing .assumptions-list').first().innerText();
    results.push('Pricing conditions bullets: ' + conditions.replace(/\n/g, ' | ').slice(0, 220));
    await page.screenshot({ path: '/tmp/qa_desktop_pricing.png', fullPage: true });
    await page.close();
  }

  // ---- Mobile pass ----
  {
    const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
    await page.goto(url, { waitUntil: 'networkidle' });
    const counterText = await page.locator('#chapter-counter').innerText();
    const counterVisible = await page.locator('#chapter-counter').isVisible();
    results.push('Mobile chapter counter visible: ' + counterVisible + ', text: ' + counterText);
    await page.click('.chapter-link[data-goto="sec-experience"]');
    await page.waitForTimeout(200);
    const counterText2 = await page.locator('#chapter-counter').innerText();
    results.push('Mobile chapter counter after nav to Experience: ' + counterText2);
    const teamAvatarTexts = await page.locator('.team-avatar').allInnerTexts();
    results.push('Team avatar initials: ' + JSON.stringify(teamAvatarTexts));
    await page.screenshot({ path: '/tmp/qa_mobile_experience.png', fullPage: true });

    await page.click('.chapter-link[data-goto="sec-overview"]');
    await page.waitForTimeout(200);
    await page.screenshot({ path: '/tmp/qa_mobile_overview.png', fullPage: true });
    await page.close();
  }

  await browser.close();
  console.log(results.join('\n'));
})().catch((e) => { console.error('SCRIPT ERROR:', e); process.exit(1); });
