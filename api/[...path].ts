export const config = {
  runtime: 'edge',
};

const HOP_BY_HOP = [
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
];

function filterHeaders(source: Headers): Headers {
  const headers = new Headers(source);
  for (const header of HOP_BY_HOP) {
    headers.delete(header);
  }
  return headers;
}

export default async function handler(req: Request): Promise<Response> {
  const backendBase = process.env.BACKEND_URL;
  if (!backendBase) {
    return new Response('Backend not configured', { status: 500 });
  }

  const incomingUrl = new URL(req.url);
  const targetUrl = new URL(incomingUrl.pathname, backendBase);
  targetUrl.search = incomingUrl.search;

  const headers = filterHeaders(req.headers);
  headers.set('x-forwarded-host', incomingUrl.host);
  headers.set('x-forwarded-proto', incomingUrl.protocol.replace(':', ''));

  const init: RequestInit = {
    method: req.method,
    headers,
    redirect: 'manual',
  };

  if (req.method !== 'GET' && req.method !== 'HEAD') {
    init.body = req.body;
  }

  let upstream: Response;
  try {
    upstream = await fetch(targetUrl.toString(), init);
  } catch (error) {
    console.error('[proxy] upstream fetch failed', error);
    return new Response('Upstream service unavailable', { status: 502 });
  }

  const responseHeaders = filterHeaders(upstream.headers);
  responseHeaders.set('access-control-expose-headers', '*');

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
}