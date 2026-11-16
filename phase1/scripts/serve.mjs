import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('../', import.meta.url));
const portIndex = process.argv.indexOf('--port');
const port = Number(portIndex === -1 ? 4173 : process.argv[portIndex + 1]);
if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Use a port between 1024 and 65535');
const files = new Map([
  ['/', 'web/index.html'], ['/index.html', 'web/index.html'],
  ['/styles.css', 'web/styles.css'], ['/app.mjs', 'web/app.mjs'],
  ['/state.mjs', 'web/state.mjs'], ['/lib/graph.mjs', 'lib/graph.mjs'],
  ['/content/sample.json', 'content/sample.json'], ['/content/graph.json', 'content/graph.json']
]);
const mime = { '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8', '.json': 'application/json; charset=utf-8' };
const server = http.createServer(async (req, res) => {
  const headers = {
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
    'Cache-Control': 'no-store',
    'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
  };
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    res.writeHead(405, { ...headers, Allow: 'GET, HEAD' }); res.end(); return;
  }
  let pathname;
  try { pathname = new URL(req.url, 'http://127.0.0.1').pathname; }
  catch { res.writeHead(400, headers); res.end(); return; }
  const file = files.get(pathname);
  if (!file) { res.writeHead(404, headers); res.end('Not found'); return; }
  try {
    const buffer = await readFile(path.join(root, file));
    res.writeHead(200, { ...headers, 'Content-Type': mime[path.extname(file)], 'Content-Length': buffer.length });
    res.end(req.method === 'HEAD' ? undefined : buffer);
  } catch {
    res.writeHead(503, { ...headers, 'Content-Type': 'text/plain; charset=utf-8' });
    res.end('ملفات العينة غير مكتملة. راجع تشغيل الخادم وملفات المحتوى.');
  }
});
server.on('error', error => {
  if (error.code === 'EADDRINUSE') console.error(`Port ${port} is busy. Try: node scripts/serve.mjs --port ${port + 1}`);
  else console.error(error.message);
  process.exitCode = 1;
});
server.listen(port, '127.0.0.1', () => console.log(`Local: http://127.0.0.1:${port}`));
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => server.close());
