import assert from 'node:assert/strict';
import {test} from 'node:test';
import {mkdtempSync, writeFileSync, readFileSync, readdirSync, mkdirSync, symlinkSync} from 'node:fs';
import {join, dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createServer} from 'node:http';
import {once} from 'node:events';
import {buildRequests, commonTokenPrefix, streamCompletion, runBranches, workspaceFile, workPath, terminal} from './shared-core.mjs';
import extension from './shared-extension.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const temp = mkdtempSync(join(here, 'test-artifacts-'));
const history = [{role: 'system', content: 'One coordinator'}, {role: 'user', content: 'Implement a parser'}];
const tasks = [{id: 'parse', instruction: 'Propose parser.js only'}, {id: 'tests', instruction: 'Propose parser.test.js only'}];
const event = (content, finish = null) => `data: ${JSON.stringify({choices: [{delta: content === null ? {} : {content}, finish_reason: finish}]})}\r\n\r\n`;
const response = (chunks, finish = 'stop') => new Response(new ReadableStream({start(controller) {
  for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk));
  controller.enqueue(new TextEncoder().encode(event(null, finish) + 'data: [DONE]\n\n')); controller.close();
}}), {status: 200});

test('workspace writes preserve existing work and literal replacement text', () => {
  workspaceFile(temp, {action: 'write', path: 'a.txt', content: 'one\ntwo'});
  assert.throws(() => workspaceFile(temp, {action: 'write', path: 'a.txt', content: 'overwrite'}), /exists/);
  workspaceFile(temp, {action: 'replace', path: 'a.txt', old: 'one', content: '$& $`'});
  assert.equal(readFileSync(join(temp, 'a.txt'), 'utf8'), '$& $`\ntwo');
  assert.match(workspaceFile(temp, {action: 'read', path: 'a.txt', line: 2}), /2: two/);
  assert.throws(() => workspaceFile(temp, {action: 'replace', path: 'a.txt', old: 'absent', content: ''}), /exactly once/);
});
test('workspace traversal and links escaping workspace are refused', () => {
  for (const path of ['../out', '..\\out', 'C:\\Windows\\win.ini']) assert.throws(() => workPath(temp, path));
  const target = mkdtempSync(join(here, 'test-artifacts-link-'));
  symlinkSync(target, join(temp, 'escape'), 'junction');
  assert.throws(() => workPath(temp, 'escape/file'), /Link leaves/);
});
test('branch messages freeze one exact shared prefix and file snapshots', () => {
  writeFileSync(join(temp, 'code.js'), 'export const value = 7;');
  const built = buildRequests({history, tasks, cwd: temp, files: ['code.js']});
  assert.deepEqual(built.requests[0].payload.messages.slice(0, -1), built.requests[1].payload.messages.slice(0, -1));
  assert.notEqual(built.requests[0].payload.messages.at(-1).content, built.requests[1].payload.messages.at(-1).content);
  assert.equal(built.requests[0].payload.tools, undefined);
  for (const {payload} of built.requests) {
    assert.equal(payload.reasoning_effort, 'low');
    assert.equal(payload.chat_template_kwargs.enable_thinking, true);
  }
  writeFileSync(join(temp, 'code.js'), 'modified after snapshot');
  assert.match(built.common.at(-1).content, /value = 7/);
  built.requests[0].payload.messages[0].content = 'changed';
  assert.equal(history[0].content, 'One coordinator');
  assert.equal(built.requests[1].payload.messages[0].content, 'One coordinator');
});
test('reject invalid task counts, duplicated IDs and missing instructions', () => {
  for (const invalid of [[], Array.from({length: 9}, (_, i) => ({id: String(i), instruction: 'x'})), [tasks[0], tasks[0]], [{id: '../x', instruction: 'x'}], [{id: 'x', instruction: ''}]])
    assert.throws(() => buildRequests({history, tasks: invalid, cwd: temp}));
});
test('rendered token prefix comparison stops exactly at first differing ID', () => {
  assert.deepEqual(commonTokenPrefix([[4, 8, 9, 1], [4, 8, 2], [4, 8, 9]]), [4, 8]);
  assert.deepEqual(commonTokenPrefix([]), []);
});
test('SSE parser handles CRLF, arbitrary chunks and live Unicode', async () => {
  const bytes = new TextEncoder().encode(event('Română\n') + event(null, 'stop') + 'data: [DONE]\n\n');
  const fetchImpl = async () => new Response(new ReadableStream({start(c) {
    for (let i = 0; i < bytes.length; i += 3) c.enqueue(bytes.slice(i, i + 3)); c.close();
  }}));
  const deltas = [];
  const result = await streamCompletion({max_tokens: 100}, {fetchImpl, onDelta: text => deltas.push(text)});
  assert.equal(result.content, 'Română\n'); assert.equal(deltas.join(''), result.content);
  assert.equal(result.receipt.done, true);
});
test('branch truncation is rejected; only explicit one-token warmup accepts length', async () => {
  const fetchImpl = async () => response([event('partial')], 'length');
  await assert.rejects(streamCompletion({max_tokens: 1}, {fetchImpl}), /did not finish normally/);
  const warm = await streamCompletion({max_tokens: 1}, {fetchImpl, warmup: true});
  assert.equal(warm.receipt.finish_reason, 'length');
});

test('reasoning streams live before answer text and never enters the code proposal', async () => {
  const thoughts = [], answers = [];
  const thinking = 'data: {"choices":[{"delta":{"reasoning_content":"Check the invariant.\\n"}}]}\n\n';
  const result = await streamCompletion({max_tokens: 100}, {
    fetchImpl: async () => response([thinking, event('export const answer = 42;')]),
    onReasoningDelta: text => thoughts.push(text), onDelta: text => answers.push(text)
  });
  assert.equal(result.reasoning, 'Check the invariant.\n');
  assert.deepEqual(thoughts, [result.reasoning]);
  assert.equal(result.content, 'export const answer = 42;');
  assert.deepEqual(answers, [result.content]);
  assert.ok(result.receipt.ttft_seconds <= result.receipt.first_content_seconds);
  const warm = await streamCompletion({max_tokens: 1}, {fetchImpl: async () => response([thinking], 'length'), warmup: true});
  assert.equal(warm.content, '');
  assert.equal(warm.receipt.first_content_seconds, null);
  assert.ok(warm.receipt.ttft_seconds !== null);
});
test('HTTP errors, in-stream errors, attempted tools and missing DONE propagate', async () => {
  await assert.rejects(streamCompletion({}, {fetchImpl: async () => new Response('bad', {status: 500})}), /HTTP 500/);
  await assert.rejects(streamCompletion({}, {fetchImpl: async () => new Response('data: {"error":{"message":"VRAM full"}}\n\n')}), /VRAM full/);
  await assert.rejects(streamCompletion({}, {fetchImpl: async () => new Response('data: {"choices":[{"delta":{"tool_calls":[{}]}}]}\n\n')}), /attempted a tool/);
  await assert.rejects(streamCompletion({}, {fetchImpl: async () => new Response(event('partial', 'stop'))}), /Incomplete/);
});

async function fixture(fn, mode = 'ok') {
  const posts = [];
  let live = 0, maxLive = 0;
  const server = createServer(async (req, res) => {
    if (req.url === '/v1/models') {
      res.setHeader('Content-Type', 'application/json');
      res.end(JSON.stringify({data: [{id: 'qwen27-shared-agent', capabilities: {synchronized_start: true}}]})); return;
    }
    let data = ''; for await (const chunk of req) data += chunk;
    const payload = JSON.parse(data); posts.push({path: req.url, payload});
    if (req.url === '/tokenize') {
      const tokens = [...JSON.stringify(payload.messages)].map(c => c.codePointAt(0));
      res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify({count: tokens.length, max_model_len: 65536, tokens})); return;
    }
    res.setHeader('Content-Type', 'text/event-stream');
    if (payload.max_tokens === 1) {res.end(event('W', 'length') + 'data: [DONE]\n\n'); return;}
    if (mode === 'fail') {res.end('data: {"error":{"message":"injected failure"}}\n\n'); return;}
    live++; maxLive = Math.max(maxLive, live);
    res.write(event('proposal '));
    const timer = setTimeout(() => {live--; res.end(event(payload.messages.at(-1).content.slice(0, 25), 'stop') +
      'data: {"usage":{"completion_tokens":12,"prompt_tokens_details":{"cached_tokens":256}}}\n\n' + 'data: [DONE]\n\n');}, 30);
    res.on('close', () => clearTimeout(timer));
  });
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  try {return await fn({baseUrl: `http://127.0.0.1:${server.address().port}`, posts, maxLive: () => maxLive});}
  finally {server.closeAllConnections(); server.close();}
}
test('real localhost fixture verifies common prefix, warming, concurrent proposals and receipts', async () => {
  await fixture(async ({baseUrl, posts, maxLive}) => {
    const events = [];
    const result = await runBranches({history, tasks, files: [], cwd: temp, runRoot: join(temp, 'runs'), coordinatorTokens: 1000,
      baseUrl, onProgress: e => events.push(e)});
    assert.equal(result.results.length, 2); assert.equal(result.summary.status, 'complete');
    assert.ok(result.summary.rendered_common_prefix_tokens > 100);
    assert.ok(maxLive() > 1);
    const generations = posts.filter(p => p.path === '/v1/chat/completions');
    for (const {payload} of posts) {
      assert.equal(payload.reasoning_effort, 'low');
      assert.equal(payload.chat_template_kwargs.enable_thinking, true);
    }
    assert.equal(generations.length, 3); assert.equal(generations[0].payload.max_tokens, 1);
    assert.equal(generations[0].payload.start_group, undefined);
    assert.deepEqual(generations.slice(1).map(p => p.payload.start_group), [
      {id: result.summary.run_id, count: 2, index: 0}, {id: result.summary.run_id, count: 2, index: 1}]);
    assert.deepEqual(generations[1].payload.messages, generations[0].payload.messages);
    assert.ok(events.some(e => e.type === 'delta'));
    assert.equal(result.results[0].receipt.usage.prompt_tokens_details.cached_tokens, 256);
    assert.ok(readFileSync(join(result.summary.directory, 'parse.proposal.txt'), 'utf8').startsWith('proposal'));
    assert.equal(JSON.parse(readFileSync(join(result.summary.directory, 'summary.json'))).status, 'complete');
  });
});
test('failure never returns successful proposals and preserves failure/partial receipts', async () => {
  await fixture(async ({baseUrl}) => {
    const runRoot = join(temp, 'failed-runs');
    await assert.rejects(runBranches({history, tasks, files: [], cwd: temp, runRoot, coordinatorTokens: 1000, baseUrl}), /injected failure/);
    const summary = JSON.parse(readFileSync(join(runRoot, readdirSync(runRoot)[0], 'summary.json')));
    assert.equal(summary.status, 'failed');
  }, 'fail');
});
test('integration headroom refusal happens before generation', async () => {
  await fixture(async ({baseUrl, posts}) => {
    await assert.rejects(runBranches({history, tasks, cwd: temp, runRoot: join(temp, 'full'), coordinatorTokens: 64000, baseUrl}), /fewer than 256/);
    assert.equal(posts.filter(p => p.path === '/v1/chat/completions').length, 0);
  });
});
test('eight branches keep the same prefix and return all eight proposals', async () => {
  await fixture(async ({baseUrl, maxLive}) => {
    const eight = Array.from({length: 8}, (_, i) => ({id: `branch${i}`, instruction: `Own file${i}.js only; propose a complete implementation.`}));
    const result = await runBranches({history, tasks: eight, cwd: temp, runRoot: join(temp, 'eight'), coordinatorTokens: 1000, baseUrl});
    assert.equal(result.results.length, 8); assert.equal(result.summary.concurrency_requested, 8);
    assert.equal(maxLive(), 8);
    assert.equal(new Set(result.results.map(r => r.id)).size, 8);
  });
});
test('cancelling during live branch output aborts the entire batch', async () => {
  await fixture(async ({baseUrl}) => {
    const controller = new AbortController();
    const runRoot = join(temp, 'live-cancelled');
    await assert.rejects(runBranches({history, tasks, cwd: temp, runRoot, coordinatorTokens: 1000, baseUrl, signal: controller.signal,
      onProgress: e => {if (e.type === 'delta') controller.abort(new Error('live user cancellation'));}}), /abort|cancellation/i);
    assert.equal(JSON.parse(readFileSync(join(runRoot, readdirSync(runRoot)[0], 'summary.json'))).status, 'cancelled');
  });
});
test('pre-cancelled batches create cancelled receipt and no HTTP requests', async () => {
  const controller = new AbortController(); controller.abort(new Error('user cancelled'));
  let calls = 0;
  const runRoot = join(temp, 'cancelled');
  await assert.rejects(runBranches({history, tasks, cwd: temp, runRoot, coordinatorTokens: 1000, signal: controller.signal,
    fetchImpl: async () => {calls++; throw new Error('must not call');}}), /user cancelled/);
  assert.equal(calls, 0);
  assert.equal(JSON.parse(readFileSync(join(runRoot, readdirSync(runRoot)[0], 'summary.json'))).status, 'cancelled');
});
test('extension registers only practical tools and context hook using installed API shape', async () => {
  const registrations = [], hooks = new Map();
  const schema = new Proxy(() => schema, {get: () => schema});
  await extension({zod: schema, setLabel() {}, on: (name, cb) => hooks.set(name, cb), registerTool: tool => registrations.push(tool)}, {Text: class {}});
  assert.deepEqual(registrations.map(t => t.name), ['workspace_file', 'workspace_terminal', 'parallel_tasks']);
  assert.ok(hooks.has('before_provider_request'));
  const branch = registrations.find(t => t.name === 'parallel_tasks');
  await assert.rejects(branch.execute('id', {tasks}, new AbortController().signal, null, {cwd: temp}), /No coordinator request/);
});
test('PowerShell native exit failures cannot be reported as success', async () => {
  const ok = await terminal(temp, {command: 'Write-Output "terminal-ok"', timeout_seconds: 10});
  assert.match(ok.output, /terminal-ok/); assert.equal(ok.code, 0);
  await assert.rejects(terminal(temp, {command: 'cmd.exe /c exit 7', timeout_seconds: 10}), /exited 1|exited 7/);
});

test('coordinator token preflight and generation use the same explicit low-thinking settings', async () => {
  const hooks = new Map(), seen = [];
  const schema = new Proxy(() => schema, {get: () => schema});
  await extension({zod: schema, setLabel() {}, on: (name, cb) => hooks.set(name, cb), registerTool() {}}, {Text: class {}});
  const original = globalThis.fetch;
  globalThis.fetch = async (_url, options) => {
    seen.push(JSON.parse(options.body));
    return Response.json({count: 3, tokens: [1, 2, 3], max_model_len: 65536});
  };
  try {
    const payload = await hooks.get('before_provider_request')({payload: {messages: history,
      reasoning_effort: 'none', chat_template_kwargs: {enable_thinking: false}}}, {model: {provider: 'TensorFold-Shared'}});
    assert.equal(payload.reasoning_effort, 'low');
    assert.equal(payload.chat_template_kwargs.enable_thinking, true);
    assert.equal(seen[0].reasoning_effort, payload.reasoning_effort);
    assert.deepEqual(seen[0].chat_template_kwargs, payload.chat_template_kwargs);
  } finally {globalThis.fetch = original;}
});
console.log(`Offline test artifacts: ${temp}`);
