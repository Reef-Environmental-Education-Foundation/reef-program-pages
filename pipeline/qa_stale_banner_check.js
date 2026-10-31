// Browser check for the stale-version banner. From the repo root:
//   node pipeline/qa_stale_banner_check.js [bookings/<slug>]   (default palmetto-bay-academy)
// Serves the repo on localhost, loads the page, and fakes version.json four ways.
// Needs playwright (already installed in the Claude Code environment).
const { chromium } = require("playwright");
const http = require("http");
const fs = require("fs");
const path = require("path");

const slug = process.argv[2] || "bookings/palmetto-bay-academy";
const root = path.resolve(__dirname, "..");
const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json" };
const server = http.createServer((req, res) => {
  const file = path.join(root, decodeURIComponent(req.url.split("?")[0]));
  if (!file.startsWith(root) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "Content-Type": types[path.extname(file)] || "application/octet-stream" });
  fs.createReadStream(file).pipe(res);
});

async function run(browser, base, label, versionJson, expectStale) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.route("**/version.json", (r) => versionJson === null
    ? r.fulfill({ status: 404, body: "" })
    : r.fulfill({ status: 200, contentType: "application/json", body: versionJson }));
  await page.goto(`${base}/${slug}/index.html`);
  await page.waitForSelector(".chapter-link");
  await page.waitForTimeout(500);
  const banner = await page.locator(".stale-banner").count();
  const pricingHidden = await page.evaluate(() => getComputedStyle(document.getElementById("sec-pricing")).display === "none"
    && !document.querySelector(".chapter-link[data-goto='sec-pricing']:not(.stale-hide)"));
  const ctaVisible = await page.evaluate(() => [...document.querySelectorAll(".cta-module")].some((n) => n.offsetParent !== null));
  const ok = expectStale ? banner === 1 && pricingHidden && !ctaVisible && errors.length === 0
                         : banner === 0 && !pricingHidden && errors.length === 0;
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}: banner=${banner} pricingHidden=${pricingHidden} ctaVisible=${ctaVisible} errors=${errors.length}`);
  if (expectStale) console.log("      " + (await page.locator(".stale-banner").innerText()).replace(/\n/g, " "));
  await page.close();
  return ok;
}

(async () => {
  await new Promise((r) => server.listen(0, r));
  const base = `http://localhost:${server.address().port}`;
  const browser = await chromium.launch();
  const results = [
    await run(browser, base, "newer version in version.json (5 > page)", '{"currentVersion": 5}', true),
    await run(browser, base, "same version", '{"currentVersion": 1}', false),
    await run(browser, base, "no version.json (404)", null, false),
    await run(browser, base, "malformed version.json", "not json", false),
  ];
  await browser.close();
  server.close();
  process.exit(results.every(Boolean) ? 0 : 1);
})();
