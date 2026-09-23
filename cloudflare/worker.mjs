export default {
  async fetch(request, env) {
    const publicURL = new URL(request.url);
    const suppliedOrigin = request.headers.get('origin');
    if (suppliedOrigin && suppliedOrigin !== publicURL.origin) {
      return new Response('Invalid request origin', {status:403});
    }
    const origin = new URL(env.ORIGIN_URL);
    if (origin.protocol !== 'https:' || !origin.hostname.endsWith('.trycloudflare.com')) {
      return new Response('Origin configuration unavailable', {status:503});
    }
    // Assign path separately: a //path must never become a user-controlled upstream host.
    const target = new URL(origin);
    target.pathname = publicURL.pathname;
    target.search = publicURL.search;
    const headers = new Headers(request.headers);
    headers.delete('host');
    headers.delete('forwarded');
    headers.delete('x-forwarded-host');
    headers.delete('x-forwarded-for');
    headers.set('x-forwarded-proto', 'https');
    if (suppliedOrigin) headers.set('origin', origin.origin);
    try {
      const upstream = await fetch(target, {
        method:request.method, headers,
        body:['GET','HEAD'].includes(request.method) ? undefined : request.body,
        redirect:'manual',
        cf:{cacheTtl:0, cacheEverything:false},
      });
      const responseHeaders = new Headers(upstream.headers);
      responseHeaders.set('cache-control', 'private, no-store');
      const location = responseHeaders.get('location');
      if (location) {
        const redirect = new URL(location, target);
        if (redirect.origin === origin.origin) {
          responseHeaders.set('location', publicURL.origin + redirect.pathname + redirect.search + redirect.hash);
        }
      }
      return new Response(upstream.body, {status:upstream.status, headers:responseHeaders});
    } catch {
      return Response.json({detail:'DUPRVision is offline. The host computer needs to reconnect.'},
                           {status:503, headers:{'cache-control':'no-store'}});
    }
  },
};
