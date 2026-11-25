/* Duck.ai X-Vqd-Hash-1 challenge solver.
 *
 * Duck.ai has no public API. Its browser sends a rotating JavaScript browser
 * check to /duckchat/v1/status and expects the solved result back in the
 * X-Vqd-Hash-1 header. This helper executes that challenge in a small DOM
 * provided by linkedom, with the same navigator/window signals a normal Chrome
 * tab reports. It is bundled to a single JS file for the MJA server.
 *
 * Usage: node duck_challenge_solver.bundle.js <challenge.js> [user-agent]
 */
const fs = require('fs');
const vm = require('vm');
const { parseHTML } = require('linkedom');

const source = fs.readFileSync(process.argv[2], 'utf8');
const userAgent = process.argv[3] || (
  'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 ' +
  '(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36'
);

const browserWindow = parseHTML('<!doctype html><html><body></body></html>');
const sandbox = {};
for (const key of Object.keys(browserWindow)) {
  try { sandbox[key] = browserWindow[key]; } catch (_) { /* read-only */ }
}
Object.defineProperty(sandbox, Symbol.toStringTag, { value: 'Window', configurable: true });
for (const name of [
  'Element', 'HTMLElement', 'HTMLDivElement', 'HTMLIFrameElement',
  'HTMLMetaElement', 'Node', 'NodeList', 'Window',
]) {
  if (typeof browserWindow[name] !== 'undefined') sandbox[name] = browserWindow[name];
}
sandbox.navigator = { userAgent, webdriver: false };
sandbox.document = browserWindow.document;
sandbox.location = { href: 'https://duck.ai/', origin: 'https://duck.ai' };
sandbox.window = sandbox;
sandbox.self = sandbox;
sandbox.top = sandbox;
sandbox.getComputedStyle = () => ({ cssText: '', getPropertyValue: () => '' });
for (const [key, value] of [
  ['__DDG_BE_VERSION__', '1.0.0'],
  ['__DDG_FE_CHAT_HASH__', 'MJA'],
  ['i3jp0', true],
  ['vz95n', true],
  ['pxjzr', true],
]) {
  sandbox[key] = value;
}
for (const name of ['Array', 'Object', 'Promise', 'Proxy', 'Symbol', 'JSON', 'Window']) {
  if (typeof sandbox[name] !== 'undefined') sandbox['_' + name] = sandbox[name];
}
if (sandbox.Element && sandbox.Element.prototype) {
  const proto = sandbox.Element.prototype;
  for (const [prop, value] of [
    ['offsetWidth', 17], ['offsetHeight', 35], ['scrollHeight', 19],
    ['clientWidth', 17], ['clientHeight', 35],
  ]) {
    Object.defineProperty(proto, prop, { get() { return value; }, configurable: true });
  }
  proto.getBoundingClientRect = function getBoundingClientRect() {
    return { width: 17, height: 35, top: 0, left: 0, right: 17, bottom: 35, x: 0, y: 0 };
  };
}
vm.createContext(sandbox);

(async () => {
  try {
    const result = await vm.runInContext(source, sandbox, { timeout: 30000 });
    process.stdout.write(JSON.stringify(result));
  } catch (error) {
    process.stdout.write(JSON.stringify({ __error: String((error && error.stack) || error) }));
  }
})();
