import {test} from 'node:test';
import assert from 'node:assert/strict';
import worker from './worker.mjs';

const env={ORIGIN_URL:'https://test.trycloudflare.com'};
test('rejects cross-origin state changes',async()=>{
  const result=await worker.fetch(new Request('https://duprvision.example.workers.dev/api/login',{
    method:'POST',headers:{origin:'https://evil.example'},body:'test'}),env);
  assert.equal(result.status,403);
});
test('streams uploads, rewrites same-origin header, keeps session cookies private',async()=>{
  const originalFetch=globalThis.fetch;
  try {
    globalThis.fetch=async(url,options)=>{
      assert.equal(url.origin,env.ORIGIN_URL);
      assert.equal(options.headers.get('origin'),env.ORIGIN_URL);
      assert.equal(await new Response(options.body).text(),'video bytes');
      return new Response('ok',{headers:{'set-cookie':'duprvision_session=test; HttpOnly; Secure; SameSite=Lax'}});
    };
    const response=await worker.fetch(new Request('https://duprvision.example.workers.dev/api/videos',{
      method:'POST',headers:{origin:'https://duprvision.example.workers.dev'},body:'video bytes'}),env);
    assert.match(response.headers.get('set-cookie'),/HttpOnly/);
    assert.equal(response.headers.get('cache-control'),'private, no-store');
  } finally {globalThis.fetch=originalFetch;}
});
test('cannot route protocol-relative paths to arbitrary hosts',async()=>{
  const originalFetch=globalThis.fetch;
  try {
    globalThis.fetch=async(url)=>{
      assert.equal(url.origin,env.ORIGIN_URL);
      return new Response('ok');
    };
    assert.equal((await worker.fetch(new Request('https://duprvision.example.workers.dev//evil.example/path'),env)).status,200);
  } finally {globalThis.fetch=originalFetch;}
});
