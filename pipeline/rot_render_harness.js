// Test harness (2026-11-04): runs assets/render.js's rotationSchedule() against
// a tiny stub DOM and prints the resulting markup. No browser or npm install.
//   node pipeline/rot_render_harness.js <render.js> <rotation.json>
const fs = require("fs");
const [, , renderPath, rotPath] = process.argv;

function Node_(tag) { this.tag = tag; this.attrs = {}; this.children = []; this.className = ""; }
Node_.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); };
Node_.prototype.appendChild = function (c) { this.children.push(c); return c; };
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;");
function ser(n) {
  if (typeof n === "string") return esc(n);
  if (n.text !== undefined) return esc(n.text);
  const a = Object.keys(n.attrs).map((k) => ` ${k}="${n.attrs[k]}"`).join("");
  const c = n.className ? ` class="${n.className}"` : "";
  return `<${n.tag}${c}${a}>` + n.children.map(ser).join("") + `</${n.tag}>`;
}
global.window = {};
global.document = {
  readyState: "loading",
  addEventListener() {},
  createElement: (t) => new Node_(t),
  createTextNode: (t) => ({ text: t }),
  getElementById: () => null,
};
let src = fs.readFileSync(renderPath, "utf8");
const hook = 'if (document.readyState === "loading")';
if (!src.includes(hook)) { console.error("hook not found"); process.exit(2); }
src = src.replace(hook, "window.__rotationSchedule = rotationSchedule;\n  " + hook);
new Function("window", "document", src)(global.window, global.document);
const rot = JSON.parse(fs.readFileSync(rotPath, "utf8"));
process.stdout.write(ser(global.window.__rotationSchedule(rot, { draft: false })));
