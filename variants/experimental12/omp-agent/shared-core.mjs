import {createHash, randomUUID} from 'node:crypto';
import {existsSync, realpathSync, statSync, readdirSync, readFileSync, writeFileSync, mkdirSync, appendFileSync} from 'node:fs';
import {resolve, relative, dirname, isAbsolute, join} from 'node:path';
import {spawn} from 'node:child_process';

export const MODEL = 'qwen27-sync-speed';
export const BASE_URL = 'http://127.0.0.1:18198';
const HEADROOM = 128;
const sha = value => createHash('sha256').update(value).digest('hex');

export function workPath(cwd, name) {
  if (!name || isAbsolute(name)) throw new Error('Use a relative workspace path.');
  const base = realpathSync(cwd), path = resolve(base, name);
  const outside = p => {const rel = relative(base, p); return rel === '..' || rel.startsWith('../') || rel.startsWith('..\\') || isAbsolute(rel);};
  if (outside(path)) throw new Error('Path leaves the workspace.');
  let ancestor = path;
  while (!existsSync(ancestor)) ancestor = dirname(ancestor);
  if (outside(realpathSync(ancestor))) throw new Error('Link leaves the workspace.');
  return path;
}

export function workspaceFile(cwd, p) {
  const path = workPath(cwd, p.path);
  if (p.action === 'read') {
    if (statSync(path).isDirectory()) return readdirSync(path).slice(0, 100).join('\n');
    const lines = readFileSync(path, 'utf8').split('\n'), start = (p.line || 1) - 1;
    const text = lines.slice(start, start + 120).map((line, i) => `${start + i + 1}: ${line}`).join('\n');
    return text.slice(0, 12000) + `\n[${lines.length} total lines${text.length > 12000 ? '; truncated at 12000 characters' : ''}]`;
  }
  if (typeof p.content !== 'string') throw new Error('content is required.');
  if (p.action === 'write') {
    if (existsSync(path)) throw new Error('File exists; use an exact unique replacement.');
    mkdirSync(dirname(path), {recursive: true});
    writeFileSync(path, p.content, {encoding: 'utf8', flag: 'wx'});
  } else if (p.action === 'replace') {
    if (!p.old) throw new Error('old must be nonempty.');
    const before = readFileSync(path, 'utf8');
    if (before.split(p.old).length !== 2) throw new Error('old must occur exactly once; read the file first.');
    writeFileSync(path, before.replace(p.old, () => p.content), 'utf8');
  } else throw new Error('Unknown action.');
  return `Saved ${p.path}; ${statSync(path).size} bytes.`;
}

export async function tokenize(payload, {baseUrl = BASE_URL, signal, fetchImpl = fetch} = {}) {
  const response = await fetchImpl(`${baseUrl}/tokenize`, {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({...payload, add_generation_prompt: true}), signal: combineSignal(signal, 30000)});
  if (!response.ok) throw new Error(`Token preflight HTTP ${response.status}: ${(await response.text()).slice(0, 2000)}`);
  const info = await response.json();
  if (!Number.isSafeInteger(info.count) || !Number.isSafeInteger(info.max_model_len) || !Array.isArray(info.tokens) || info.count !== info.tokens.length)
    throw new Error('Incomplete tokenizer receipt; token IDs and context size are required.');
  return info;
}

function combineSignal(signal, timeout) {
  return signal ? AbortSignal.any([signal, AbortSignal.timeout(timeout)]) : AbortSignal.timeout(timeout);
}

export function commonTokenPrefix(sequences) {
  if (!sequences.length) return [];
  let n = Math.min(...sequences.map(s => s.length));
  for (let i = 0; i < n; i++) if (sequences.some(s => s[i] !== sequences[0][i])) {n = i; break;}
  return sequences[0].slice(0, n);
}

const WORKER_CONTRACT = `You are an internal read-only branch of ONE coding agent. The conversation above is shared history.
The following file snapshots and constraints are identical for all branches. Only your final task differs. Write all reasoning, proposals, comments and explanations in English; preserve quoted source text and required test data.
Do not execute tools, write files, claim tests ran, or address the user. Return a concrete proposal for your assigned independent task, including exact paths and code changes when useful, assumptions and checks the coordinator must run.
Other branches may work on different tasks. Do not redesign their contracts or change their files. A hard output token limit applies: prioritize the essential patch and checks, keep prose short, and close all code before finishing. Follow the task's requested output format exactly. When it requests code only, do not append prose, assumptions or test checklists. The coordinator alone integrates changes and runs tools.`;

export function buildRequests({history, tasks, sharedContext = '', files = [], cwd, maxTokens = 4096}) {
  if (!Array.isArray(history) || !history.length) throw new Error('No captured coordinator history.');
  if (!Array.isArray(tasks) || tasks.length < 1 || tasks.length > 16) throw new Error('Provide 1 to 16 independent tasks.');
  if (new Set(tasks.map(t => t.id)).size !== tasks.length) throw new Error('Task IDs must be unique.');
  for (const task of tasks) {
    if (!/^[a-zA-Z0-9_-]{1,40}$/.test(task.id) || !task.instruction?.trim()) throw new Error('Invalid task ID or empty instruction.');
    if (task.max_tokens !== undefined && (!Number.isSafeInteger(task.max_tokens) || task.max_tokens < 256 || task.max_tokens > 6144))
      throw new Error('Task max_tokens must be an integer from 256 to 6144.');
  }
  const snapshots = files.map(name => {
    const path = workPath(cwd, name);
    if (!statSync(path).isFile()) throw new Error(`Snapshot is not a file: ${name}`);
    if (statSync(path).size > 256000) throw new Error(`Snapshot exceeds 256000 bytes: ${name}; provide a smaller file or shared_context excerpt.`);
    return {path: name, content: readFileSync(path, 'utf8')};
  });
  const common = structuredClone(history);
  common.push({role: 'user', content: `${WORKER_CONTRACT}\n\nSHARED CONSTRAINTS:\n${sharedContext}\n\nSHARED FILE SNAPSHOTS:\n${JSON.stringify(snapshots)}`});
  return {common, commonMessagesSha256: sha(JSON.stringify(common)), snapshots: snapshots.map(f => ({path: f.path, sha256: sha(f.content)})),
    requests: tasks.map(task => ({id: task.id, payload: {model: MODEL, messages: [...structuredClone(common),
      {role: 'user', content: `BRANCH TASK ${task.id}:\n${task.instruction}\n\nReturn a complete bounded proposal. Tools and filesystem writes are unavailable.`}],
      temperature: 0, reasoning_effort: 'low', chat_template_kwargs: {enable_thinking: true},
      max_tokens: Math.min(task.max_tokens ?? maxTokens, maxTokens), stream: true, stream_options: {include_usage: true}}}))};
}

// Parse complete SSE events across arbitrary transport boundaries, including CRLF.
export async function streamCompletion(payload, {baseUrl = BASE_URL, signal, onDelta = () => {}, onReasoningDelta = () => {}, onEvent = () => {}, fetchImpl = fetch, warmup = false} = {}) {
  const started = performance.now();
  const response = await fetchImpl(`${baseUrl}/v1/chat/completions`, {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload), signal: combineSignal(signal, 600000)});
  if (!response.ok) throw new Error(`Completion HTTP ${response.status}: ${(await response.text()).slice(0, 2000)}`);
  if (!response.body) throw new Error('Completion has no streaming body.');
  const decoder = new TextDecoder();
  let pending = '', content = '', reasoning = '', finish = null, done = false, first = null, firstContent = null, usage = {}, runtime = {};
  const processLine = line => {
    if (!line.startsWith('data:')) return;
    const data = line.slice(5).trim();
    if (!data) return;
    if (data === '[DONE]') {done = true; return;}
    const event = JSON.parse(data);
    onEvent(event);
    if (event.error) throw new Error(`Stream error: ${JSON.stringify(event.error)}`);
    if (event.usage) usage = event.usage;
    if (event.tensorfold) Object.assign(runtime, event.tensorfold);
    for (const choice of event.choices || []) {
      if (choice.delta?.tool_calls?.length) throw new Error('Read-only branch attempted a tool call; no tool was executed.');
      const thought = choice.delta?.reasoning_content;
      if (thought) {first ??= performance.now(); reasoning += thought; onReasoningDelta(thought);}
      const delta = choice.delta?.content;
      if (delta) {first ??= performance.now(); firstContent ??= performance.now(); content += delta; onDelta(delta);}
      finish = choice.finish_reason || finish;
    }
  };
  for await (const chunk of response.body) {
    pending += decoder.decode(chunk, {stream: true});
    let end;
    while ((end = pending.indexOf('\n')) >= 0) {processLine(pending.slice(0, end).replace(/\r$/, '')); pending = pending.slice(end + 1);}
    if (done) break;
  }
  pending += decoder.decode();
  if (pending.trim()) processLine(pending.replace(/\r$/, ''));
  const receipt = {done, finish_reason: finish, usage, runtime, elapsed_seconds: (performance.now() - started) / 1000,
    ttft_seconds: first === null ? null : (first - started) / 1000,
    first_content_seconds: firstContent === null ? null : (firstContent - started) / 1000, actual_max_tokens: payload.max_tokens};
  if (!done || (!warmup && !content.trim())) throw new Error('Incomplete or empty branch response.');
  if (finish !== 'stop' && !(warmup && finish === 'length')) throw new Error(`Branch did not finish normally: ${finish || 'missing finish_reason'}. Partial output must not be integrated as complete.`);
  return {content, reasoning, receipt};
}

export function proposalText(results, summary) {
  const lead = `Read-only proposals complete: ${results.length}/${summary.tasks.length}. No project files were changed by branches.\n` +
    `Verified identical rendered prefix: ${summary.rendered_common_prefix_tokens} tokens; SHA256 ${summary.rendered_common_prefix_sha256}.\n` +
    `Receipts: ${summary.directory}\nIntegrate the proposals, resolve conflicts, run actual checks and then respond to the user.\n\n`;
  return lead + (summary.delivery === 'files'
    ? `Complete proposals are saved in these UTF-8 files. Read or extract them from disk; do not invent missing code.\n` +
      results.map(r => `${r.id}: ${join(summary.directory, r.id + '.proposal.txt')}`).join('\n')
    : results.map(r => `=== ${r.id} ===\n${r.content}`).join('\n\n'));
}

export async function runBranches({history, tasks, sharedContext, files, cwd, runRoot, coordinatorTokens, maxTokens = 4096, delivery = 'inline', signal,
  onProgress = () => {}, baseUrl = BASE_URL, fetchImpl = fetch}) {
  if (!['inline', 'files'].includes(delivery)) throw new Error('Unknown proposal delivery mode.');
  const runId = `${new Date().toISOString().replace(/[:.]/g, '-')}-${randomUUID().slice(0, 8)}`;
  const directory = join(runRoot, runId);
  mkdirSync(directory, {recursive: true});
  const controller = new AbortController();
  const combined = signal ? AbortSignal.any([signal, controller.signal]) : controller.signal;
  const options = {baseUrl, fetchImpl, signal: combined};
  const built = buildRequests({history, tasks, sharedContext, files, cwd, maxTokens});
  const record = (name, value) => writeFileSync(join(directory, name), JSON.stringify(value, null, 2), 'utf8');
  const log = event => {appendFileSync(join(directory, 'events.jsonl'), JSON.stringify({time: Date.now(), ...event}) + '\n'); onProgress(event);};
  const started = performance.now();
  const summary = {run_id: runId, directory, status: 'preflight', tasks: tasks.map(t => t.id), common_messages_sha256: built.commonMessagesSha256,
    file_snapshots: built.snapshots, reasoning_effort: 'low', enable_thinking: true,
    concurrency_requested: tasks.length, scheduler_controls_gpu_admission: true, delivery, coordinator_tokens: coordinatorTokens, branches: []};
  const results = new Array(tasks.length);
  try {
    if (combined.aborted) throw combined.reason;
    if (tasks.length > 1) {
      const discovery = await fetchImpl(`${baseUrl}/v1/models`, {signal: combineSignal(combined, 10000)});
      if (!discovery.ok || !(await discovery.json()).data?.find(m => m.id === MODEL)?.capabilities?.synchronized_start)
        throw new Error('Runtime does not support synchronized start. Restart it with the current native binary.');
    }
    // The real renderer is the authority; compare its token IDs before any generation.
    const commonInfo = await tokenize({model: MODEL, messages: built.common,
      reasoning_effort: 'low', chat_template_kwargs: {enable_thinking: true}}, options);
    const infos = [];
    for (const r of built.requests) infos.push(await tokenize(r.payload, options));
    const commonIds = commonTokenPrefix([commonInfo.tokens, ...infos.map(i => i.tokens)]);
    if (!commonIds.length) throw new Error('Renderer produced no shared token prefix.');
    summary.rendered_common_prefix_tokens = commonIds.length;
    summary.rendered_common_prefix_sha256 = sha(JSON.stringify(commonIds));
    record('common-prefix.tokens.json', commonIds);
    record('common-messages.json', built.common);
    // Leave space for all proposals, tool framing and the coordinator's next response.
    const window = Math.min(...infos.map(i => i.max_model_len));
    if (!Number.isSafeInteger(coordinatorTokens) || coordinatorTokens < 0) throw new Error('Coordinator token count is required.');
    const integrationBudget = Math.floor((window - coordinatorTokens - 8192) / tasks.length);
    if (integrationBudget < 256) throw new Error('Context leaves fewer than 256 handoff tokens per task. Compact history or reduce tasks.');
    // File handoff returns bounded paths, not every generated reasoning/answer token.
    // The coordinator's ordinary request preflight still checks any later file reads.
    const proposalBudget = delivery === 'files' ? maxTokens : integrationBudget;
    for (const [i, r] of built.requests.entries()) {
      if (commonIds.length < infos[i].tokens.length) r.payload.shared_prefixes = [commonIds.length];
      r.payload.max_tokens = Math.min(r.payload.max_tokens, proposalBudget, infos[i].max_model_len - infos[i].count - HEADROOM);
      if (r.payload.max_tokens < 256) throw new Error(`Task ${r.id}: context leaves fewer than 256 proposal tokens. Compact history or reduce tasks/shared files.`);
      record(`${r.id}.request.json`, r.payload);
    }
    summary.preflight = infos.map((info, i) => ({id: tasks[i].id, prompt_tokens: info.count, max_model_len: info.max_model_len,
      max_tokens: built.requests[i].payload.max_tokens, headroom: HEADROOM}));
    summary.requested_total_completion_tokens = built.requests.reduce((sum, r) => sum + r.payload.max_tokens, 0);
    log({type: 'prefix_ready', tokens: commonIds.length, sha256: summary.rendered_common_prefix_sha256, directory});
    summary.status = 'warming'; record('summary.json', summary); log({type: 'phase', phase: 'Warming common prefix'});
    // One real request publishes the native cache's chunk cuts; no reuse is assumed from the coordinator.
    const warm = await streamCompletion({...built.requests[0].payload, max_tokens: 1}, {...options, warmup: true, onEvent: event =>
      appendFileSync(join(directory, 'warm.events.jsonl'), JSON.stringify(event) + '\n')});
    summary.warmup = warm.receipt;
    summary.status = 'running'; log({type: 'phase', phase: `Prefilling ${tasks.length} branches · native start barrier`});
    const generationStarted = performance.now();
    const starts = [], firstOutputs = [], firstContents = []; let decoding = false;
    const noteOutput = i => {
      firstOutputs[i] ??= performance.now();
      if (!decoding) {decoding = true; log({type: 'phase', phase: `Thinking low / decoding ${tasks.length} synchronized branches`});}
    };
    const settled = await Promise.allSettled(built.requests.map(async (r, i) => {
      if (tasks.length > 1) r.payload.start_group = {id: runId, count: tasks.length, index: i};
      record(`${r.id}.request.json`, r.payload);
      starts[i] = performance.now();
      log({type: 'branch_start', id: r.id});
      try {
        const result = await streamCompletion(r.payload, {...options, onReasoningDelta: text => {
          noteOutput(i);
          appendFileSync(join(directory, `${r.id}.reasoning.txt`), text, 'utf8'); log({type: 'reasoning_delta', id: r.id, text});
        }, onDelta: text => {
          noteOutput(i); firstContents[i] ??= performance.now();
          appendFileSync(join(directory, `${r.id}.partial.txt`), text, 'utf8'); log({type: 'delta', id: r.id, text});
        }, onEvent: event => appendFileSync(join(directory, `${r.id}.events.jsonl`), JSON.stringify(event) + '\n')});
        results[i] = {id: r.id, ...result};
        writeFileSync(join(directory, `${r.id}.proposal.txt`), result.content, 'utf8');
        record(`${r.id}.receipt.json`, result.receipt);
        log({type: 'branch_end', id: r.id, receipt: result.receipt});
      } catch (error) {
        record(`${r.id}.failure.json`, {error: String(error)}); log({type: 'branch_error', id: r.id, error: String(error)});
        controller.abort(error); throw error;
      }
    }));
    const failure = settled.find(s => s.status === 'rejected');
    if (failure) throw failure.reason;
    summary.status = 'complete'; summary.branches = results.map(r => ({id: r.id, ...r.receipt}));
    summary.synchronized_start = {mechanism: 'native prefill barrier before the first shared decode round',
      http_start_spread_ms: Math.max(...starts) - Math.min(...starts),
      first_output_spread_ms: Math.max(...firstOutputs) - Math.min(...firstOutputs),
      first_output_scope: 'First reasoning or answer text; answer text may start later after each branch finishes thinking.',
      first_content_spread_ms: Math.max(...firstContents) - Math.min(...firstContents)};
    summary.generation_seconds = (performance.now() - generationStarted) / 1000;
    summary.completion_tokens = results.reduce((count, r) => count + (r.receipt.usage.completion_tokens || 0), 0);
    summary.reasoning_tokens = results.reduce((count, r) => count + (r.receipt.usage.completion_tokens_details?.reasoning_tokens || 0), 0);
    summary.non_reasoning_completion_tokens = summary.completion_tokens - summary.reasoning_tokens;
    summary.aggregate_tokens_per_second = summary.completion_tokens / summary.generation_seconds;
    summary.timing_scope = 'Reasoning and answer tokens over branch HTTP wall time including prefill, streaming and receipts; excludes token preflight, warm seed and coordinator integration.';
    summary.elapsed_seconds = (performance.now() - started) / 1000;
    record('summary.json', summary);
    log({type: 'batch_end', tokens: summary.completion_tokens, seconds: summary.generation_seconds,
      tokens_per_second: summary.aggregate_tokens_per_second});
    return {results, summary};
  } catch (error) {
    controller.abort(error);
    summary.status = combined.aborted && signal?.aborted ? 'cancelled' : 'failed';
    summary.error = String(error); summary.elapsed_seconds = (performance.now() - started) / 1000;
    record('summary.json', summary);
    throw new Error(`${summary.error}\nBranch receipts and partial outputs: ${directory}`, {cause: error});
  }
}

export async function terminal(cwd, {command, timeout_seconds = 120}, {signal, onDelta = () => {}} = {}) {
  if (!command?.trim()) throw new Error('command is required.');
  if (signal?.aborted) throw signal.reason;
  return new Promise((accept, reject) => {
    const script = `[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); $OutputEncoding=[Console]::OutputEncoding; $ErrorActionPreference='Stop'; $LASTEXITCODE=0; & {\n${command}\n}; if (-not $?) {exit 1}; if ($LASTEXITCODE -ne 0) {exit $LASTEXITCODE}`;
    const child = spawn('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script], {cwd, windowsHide: true});
    let output = '', stopped = null;
    const stop = reason => {
      if (stopped) return;
      stopped = reason;
      if (child.pid) {
        const killer = spawn('taskkill.exe', ['/pid', String(child.pid), '/t', '/f'], {windowsHide: true, stdio: 'ignore'});
        killer.on('error', () => child.kill());
      } else child.kill();
    };
    const cancel = () => stop('cancelled');
    signal?.addEventListener('abort', cancel, {once: true});
    const timer = setTimeout(() => stop('timed out'), timeout_seconds * 1000);
    const add = chunk => {const text = chunk.toString(); output = (output + text).slice(-24000); onDelta(text);};
    child.stdout.on('data', add); child.stderr.on('data', add);
    child.on('error', error => {clearTimeout(timer); signal?.removeEventListener('abort', cancel); reject(error);});
    child.on('close', code => {
      clearTimeout(timer); signal?.removeEventListener('abort', cancel);
      if (stopped || code !== 0) reject(new Error(`PowerShell ${stopped || `exited ${code}`}\n${output}`));
      else accept({code, output});
    });
    if (signal?.aborted) cancel();
  });
}
