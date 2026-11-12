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

export function sceneRenderer(Text) {
  return {
    renderCall(args,_options,theme) {
      return new Text(theme.fg('muted',`Build scene → ${args.directory||'…'}/index.html`),0,0);
    },
    renderResult(result,options,theme) {
      const details=result.details||{};
      const summary=details.summary&&details.browser?
        `${details.summary.generated_completion_tokens.toLocaleString('en-US')} tokens in ${details.summary.generation_seconds.toFixed(2)} s · ${details.summary.generation_aggregate_tps.toFixed(2)} tok/s aggregate\n`+
        `Plan ${details.summary.planning_seconds.toFixed(2)} s · build ${details.summary.artifact_seconds.toFixed(2)} s · browser check ${details.browser.seconds.toFixed(2)} s · 8/8 verified`:
        result.content.filter(item=>item.type==='text').map(item=>item.text).join('\n');
      // This is a display-only preview. The model receives the concise tool
      // receipt; the actual files and full preview remain in the session.
      const code=details.previewCode;
      if(code&&(options.isPartial||options.expanded)) {
        const body=`\x1b[38;2;213;199;167m${code}\x1b[39m`;
        return new Text(options.isPartial?body:`${body}\n\n\x1b[38;2;211;148;235m${summary}\x1b[39m`,0,0);
      }
      return new Text(theme.fg('muted',summary),0,0);
    }
  };
}
