// Append complete source lines as they arrive from ALL streams. Keeping one
// unfinished line per file prevents fragments from different files mixing.
// There is no file-order gate or playback queue; the final files stay separate.
export class LiveCodeFeed {
  constructor() { this.streams=new Map(); this.text=''; this.received=0; this.lines=0; }
  push(file,delta) {
    let state=this.streams.get(file);
    if(!state){state={pending:'',received:0,shown:0};this.streams.set(file,state);}
    state.received+=delta.length;this.received+=delta.length;state.pending+=delta;
    let end;
    while((end=state.pending.indexOf('\n'))!==-1) {
      this.emit(file,state,state.pending.slice(0,end));state.pending=state.pending.slice(end+1);
    }
  }
  emit(file,state,line) {
    line=line.replace(/\r$/,'');
    if(/^\s*```(?:javascript|js|typescript)?\s*$/.test(line))return;
    this.text+=`${file} │ ${line}\n`;state.shown+=line.length;this.lines++;
  }
  finish(file) {
    const state=this.streams.get(file);
    if(state?.pending){this.emit(file,state,state.pending);state.pending='';}
  }
  snapshot() {
    return {receivedChars:this.received,shownLines:this.lines,
      streams:Object.fromEntries([...this.streams].map(([file,s])=>[file,{received:s.received,shown:s.shown,pending:s.pending.length}]))};
  }
}

export function branchRenderer(Text) {
  return {
    renderCall(args, _options, theme) {
      return new Text(theme.fg('muted', `Shared context → ${args.tasks?.length || '…'} read-only branches`), 0, 0);
    },
    renderResult(result, options, theme) {
      const details = result.details || {};
      const summary = details.summary;
      const message = summary ? `${summary.branches.length}/${summary.tasks.length} proposals · ${summary.completion_tokens.toLocaleString('en-US')} tokens in ${summary.generation_seconds.toFixed(2)} s · ${summary.aggregate_tokens_per_second.toFixed(1)} tok/s aggregate\n` +
        `Shared prefix ${summary.rendered_common_prefix_tokens.toLocaleString('en-US')} tokens · coordinator integrates and verifies next` +
        (summary.reasoning_effort ? `\nThinking ${summary.reasoning_effort} · ${summary.reasoning_tokens.toLocaleString('en-US')} reasoning tokens included` : '') +
        (summary.synchronized_start ? `\nNative synchronized start · first reasoning/answer spread ${summary.synchronized_start.first_output_spread_ms.toFixed(1)} ms` : '') :
        result.content.filter(item => item.type === 'text').map(item => item.text).join('\n');
      if (details.previewCode && (options.isPartial || options.expanded)) {
        const code = `\x1b[38;2;213;199;167m${details.previewCode}\x1b[39m`;
        return new Text(options.isPartial ? code : `${code}\n\n\x1b[38;2;211;148;235m${message}\x1b[39m`, 0, 0);
      }
      return new Text(theme.fg('muted', message), 0, 0);
    }
  };
}
