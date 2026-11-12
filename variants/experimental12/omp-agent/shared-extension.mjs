import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {appendFileSync} from 'node:fs';
import {tokenize, runBranches, proposalText, workspaceFile, terminal} from './shared-core.mjs';
import {attachLiveStatus} from './live-status.mjs';
import {LiveCodeFeed, branchRenderer} from './branch-view.mjs';

const appRoot = dirname(fileURLToPath(import.meta.url));

export default async function sharedAgent(pi, tui) {
  const {Text} = tui || await import('@oh-my-pi/pi-tui');
  const liveStatus = attachLiveStatus(pi);
  const z = pi.zod;
  let latest = null;
  let phase = 'Ready';
  let activeBatch = false, activeTerminal = false;
  const eventLog = process.env.SHARED_AGENT_EVENTS;
  const log = event => {if (eventLog) appendFileSync(eventLog, JSON.stringify({time: Date.now(), ...event}) + '\n');};
  pi.setLabel('Qwen shared-context agent');
  pi.on('before_provider_request', async (event, ctx) => {
    if (ctx.model?.provider !== 'TensorFold-Shared') return;
    const payload = {...event.payload, reasoning_effort: 'low',
      chat_template_kwargs: {...event.payload.chat_template_kwargs, enable_thinking: true}};
    const info = await tokenize(payload);
    const available = info.max_model_len - info.count - 128;
    if (available < 256) throw new Error('Context is full. Compact this conversation before continuing; history will not be silently dropped.');
    const next = {...payload, max_tokens: Math.min(payload.max_tokens || 8192, available)};
    latest = {messages: structuredClone(payload.messages), count: info.count, window: info.max_model_len};
    log({type: 'coordinator_preflight', prompt_tokens: info.count, max_tokens: next.max_tokens,
      reasoning_effort: next.reasoning_effort, enable_thinking: next.chat_template_kwargs.enable_thinking});
    return next;
  });
  pi.on('session_start', (_event, ctx) => {
    latest = null;
    if (ctx.hasUI) {ctx.ui.setToolsExpanded(true); ctx.ui.setStatus('shared-agent', 'Thinking LOW | English | 64K | native synchronized branches');}
  });
  pi.on('agent_start', () => {latest = null;});
  for (const type of ['agent_start', 'agent_end', 'tool_call', 'tool_result']) pi.on(type, event => log({type, event}));

  pi.registerTool({
    name: 'workspace_file', label: 'Workspace file', loadMode: 'essential',
    description: 'Coordinator-only file access: read up to 120 lines/12000 characters or list a directory; create a NEW file; replace one exact unique old string. Relative paths inside the current workspace. Preserve existing work.',
    parameters: z.object({action: z.enum(['read', 'write', 'replace']), path: z.string(), content: z.string().optional(), old: z.string().optional(), line: z.number().int().min(1).optional()}),
    async execute(_id, p, signal, _update, ctx) {
      if (signal?.aborted) throw signal.reason;
      if (p.action !== 'read' && (activeBatch || activeTerminal)) throw new Error('A branch batch or terminal is active; wait before writing project files.');
      return {content: [{type: 'text', text: workspaceFile(ctx.cwd, p)}], details: {path: p.path, action: p.action}};
    }
  });
  pi.registerTool({
    name: 'workspace_terminal', label: 'Workspace terminal', loadMode: 'essential',
    description: 'Coordinator-only PowerShell in the working directory for searches, scripts, builds and tests. Runs a real command and returns actual output/exit status. Use quoted LiteralPath for file operations. Do not modify files while parallel_tasks is running. No destructive operations, publication, spending, or services outside user authorization.',
    parameters: z.object({command: z.string().min(1), timeout_seconds: z.number().int().min(1).max(300).optional()}),
    async execute(_id, p, signal, update, ctx) {
      if (activeBatch || activeTerminal) throw new Error('Wait for the active branch batch/terminal before running another command.');
      activeTerminal = true;
      let preview = '', last = 0;
      try {
        const result = await terminal(ctx.cwd, p, {signal, onDelta: text => {
          preview = (preview + text).slice(-12000);
          if (performance.now() - last > 100) {last = performance.now(); update?.({content: [{type: 'text', text: preview}]});}
        }});
        return {content: [{type: 'text', text: `Exit ${result.code}\n${result.output || '[no output]'}`}], details: {exit_code: result.code}};
      } finally {activeTerminal = false;}
    }
  });
  pi.registerTool({
    name: 'parallel_tasks', label: 'Shared-context branches', loadMode: 'essential',
    ...branchRenderer(Text),
    description: 'Run 1 to 16 independent READ-ONLY proposals against one frozen copy of this conversation and identical shared file snapshots. Task-specific suffixes differ; rendered common token prefix is verified and recorded. Workers have no tools or project writes. The server admits branches as VRAM permits; sixteen is the experimental API cap, not a memory guarantee. The selected profile has twelve lanes; actual group admission still depends on prompt and output reservations. For large batches use delivery="files" to return paths to complete saved proposals instead of putting every body into the conversation. Each task may set max_tokens below the batch ceiling to allocate more output to complex tasks without reserving that amount for every branch. Give disjoint file ownership/contracts. Results return here; YOU integrate, run real checks and finish the same conversation. Use only where independent tasks help; do simple/dependent work directly.',
    parameters: z.object({tasks: z.array(z.object({id: z.string().regex(/^[a-zA-Z0-9_-]{1,40}$/), instruction: z.string().min(1),
      max_tokens: z.number().int().min(256).max(6144).optional()})).min(1).max(16),
      shared_context: z.string().optional(), shared_files: z.array(z.string()).max(24).optional(),
      delivery: z.enum(['inline', 'files']).optional(), max_tokens: z.number().int().min(256).max(6144).optional()}),
    async execute(_id, p, signal, update, ctx) {
      if (activeBatch || activeTerminal) throw new Error('Wait for the active branch batch/terminal; at most one branch batch is allowed.');
      if (!latest) throw new Error('No coordinator request captured in this turn; shared history is unavailable.');
      activeBatch = true;
      const frozen = structuredClone(latest);
      const feed = new LiveCodeFeed();
      const completed = new Set();
      let last = 0;
      const show = (force = false) => {
        if (!force && performance.now() - last < 80) return;
        last = performance.now();
        update?.({content: [{type: 'text', text: phase}], details: {phase, previewCode: feed.text}});
      };
      try {
        const {results, summary} = await runBranches({history: frozen.messages, coordinatorTokens: frozen.count, tasks: p.tasks,
          sharedContext: p.shared_context || '', files: p.shared_files || [], cwd: ctx.cwd, runRoot: join(appRoot, 'runs'),
          maxTokens: p.max_tokens || 4096, delivery: p.delivery || 'inline', signal, onProgress: event => {
            log({type: 'branch_event', ...event});
            if (event.type === 'phase') {phase = event.phase; liveStatus.setPhase(phase); show(true);}
            if (event.type === 'reasoning_delta') {
              feed.push(`${event.id}:think`, event.text); show();
            }
            if (event.type === 'delta') {
              feed.finish(`${event.id}:think`);
              feed.push(event.id, event.text);
              show();
            }
            if (event.type === 'branch_end' || event.type === 'branch_error') {
              feed.finish(`${event.id}:think`);
              feed.finish(event.id);
              if (event.type === 'branch_end') completed.add(event.id);
              phase = event.type === 'branch_end' ? `Generating ${completed.size}/${p.tasks.length}` : `Branch error: ${event.id}`;
              liveStatus.setPhase(phase); show(true);
            }
          }});
        phase = 'Integrating proposals'; liveStatus.setPhase(phase); show(true);
        const text = proposalText(results, summary);
        return {content: [{type: 'text', text}], details: {summary, previewCode: feed.text}};
      } finally {activeBatch = false; ctx.ui?.setWorkingMessage?.();}
    }
  });
}
