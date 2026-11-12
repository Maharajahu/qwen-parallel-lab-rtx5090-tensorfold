import { appendFileSync } from 'node:fs';
import { dirname, join } from 'node:path';

// /v1/load is a single native scheduler snapshot. `decode` excludes each
// request's first token (produced by prefill); it is not a character estimate.
export class LiveMeter {
  constructor() { this.reset(); }
  reset() { this.instance=null; this.base=null; this.samples=[]; this.latest=null; this.available=false; }
  sample(load, now) {
    const values=[load?.tokens?.decode,load?.tokens?.prefill_compute,load?.busy_us?.prefill,load?.running,load?.waiting,load?.lanes];
    if(load?.model!=='qwen27-shared-agent'||typeof load.instance!=='string'||load.parked||
      values.some(n=>!Number.isSafeInteger(n)||n<0)||load.lanes<1) throw new Error('Incomplete local scheduler counters');
    const row={time:now,decode:load.tokens.decode,prefill:load.tokens.prefill_compute,prefillUs:load.busy_us.prefill};
    const previous=this.samples.at(-1);
    const reset=this.instance!==null&&(load.instance!==this.instance||row.decode<previous?.decode||row.prefill<previous?.prefill||row.prefillUs<previous?.prefillUs);
    if(this.instance===null||reset) { this.base=row; this.samples=[]; }
    else if(!this.available) this.samples=[]; // Retain totals, but restart the live-rate window after a gap.
    this.instance=load.instance;
    this.samples.push(row);
    while(this.samples.length>2&&this.samples[1].time<=now-1000)this.samples.shift();
    const first=this.samples[0],seconds=(now-first.time)/1000;
    const prefilled=row.prefill-this.base.prefill,prefillSeconds=(row.prefillUs-this.base.prefillUs)/1e6;
    this.latest={decoded:row.decode-this.base.decode,rate:load.running&&seconds>0?(row.decode-first.decode)/seconds:0,
      prefilled,prefillSeconds,prefillRate:prefillSeconds>0?prefilled/prefillSeconds:null,
      running:load.running,waiting:load.waiting,lanes:load.lanes,reset};
    this.available=true;
    return this.latest;
  }
  unavailable() { this.available=false; }
}

export function statusLines(meter, phase, seconds, active) {
  if(!meter.available)return [`TensorFold | ${phase} | telemetry unavailable | ${seconds.toFixed(1)} s`];
  const s=meter.latest;
  const rate=active?s.rate:0, prefill=s.prefillRate===null?'—':s.prefillRate.toLocaleString('en-US',{maximumFractionDigits:0});
  return [`TensorFold · ${s.lanes} lanes | decode ${rate.toFixed(1)} tok/s · ${s.decoded.toLocaleString('en-US')} tok | ${seconds.toFixed(1)} s | ${s.reset?'counter reset':phase}`,
    `prefill avg ${prefill} tok/s · ${s.prefilled.toLocaleString('en-US')} tok · ${s.prefillSeconds.toFixed(2)} s | ${s.running}/${s.lanes} active · ${s.waiting} queued`];
}

export function statusText(...args) { return statusLines(...args).join(' | '); }

export function endPhase(lastMessage, toolErrors) {
  if (lastMessage?.stopReason === 'aborted') return 'Stopped';
  if (lastMessage?.stopReason === 'error') return 'Error';
  return toolErrors ? `Done · ${toolErrors} tool error${toolErrors === 1 ? '' : 's'} observed` : 'Done';
}

export function attachLiveStatus(pi) {
  const meter=new LiveMeter();
  let context,active=false,phase='Ready',started=0,elapsed=0,toolErrors=0,generation=0,inflight=null,stopped=false;
  const logPath=process.env.SHARED_AGENT_EVENTS?join(dirname(process.env.SHARED_AGENT_EVENTS),'live-metrics.jsonl'):null;
  function render() {
    if(!context?.hasUI||stopped)return;
    const seconds=active?(performance.now()-started)/1000:elapsed;
    const lines=statusLines(meter,phase,seconds,active),text=lines.join('\n');
    context.ui.setWidget('tensorfold-live',lines.map((line,i)=>`\x1b[38;2;${i?'159;141;183':'211;148;235'}m${line}\x1b[39m`),{placement:'aboveEditor'});
    if(logPath)appendFileSync(logPath,JSON.stringify({time:Date.now(),phase,active,seconds,text,
      available:meter.available,snapshot:meter.latest})+'\n');
  }
  function poll() {
    if(inflight)return inflight;
    const currentGeneration=generation;
    inflight=(async()=>{
      try {
        const response=await fetch('http://127.0.0.1:18192/v1/load',{signal:AbortSignal.timeout(1500)});
        if(!response.ok)throw new Error(`Scheduler HTTP ${response.status}`);
        const load=await response.json();
        if(currentGeneration!==generation||stopped)return;
        meter.sample(load,performance.now());
      } catch {
        if(currentGeneration!==generation||stopped)return;
        meter.unavailable();
      } finally {
        if(currentGeneration===generation&&!stopped)render();
        inflight=null;
      }
    })();
    return inflight;
  }
  pi.on('session_start',async(_event,ctx)=>{
    context=ctx;
    if(!ctx.hasUI||ctx.model?.provider!=='TensorFold-Shared')return;
    ctx.ui.setStatus('tensorfold-live',undefined);
    ctx.ui.setToolsExpanded(true);
    await poll();
    ctx.setInterval(()=>{if(active||meter.latest?.running||meter.latest?.waiting)return poll();},250);
  });
  pi.on('agent_start',async(_event,ctx)=>{
    if(!ctx.hasUI||ctx.model?.provider!=='TensorFold-Shared')return;
    if(inflight)await inflight;
    context=ctx;generation++;meter.reset();active=true;toolErrors=0;started=performance.now();elapsed=0;phase='Agent';
    await poll();
  });
  pi.on('tool_call',event=>{
    if(!active)return;
    phase=event.toolName==='parallel_tasks'?'Shared branches':event.toolName==='workspace_terminal'?'Checking':'Files';render();
  });
  pi.on('tool_result',event=>{
    if(!active)return;
    if(event.isError)toolErrors++;phase=event.isError?'Tool error':'Reply';render();
  });
  pi.on('agent_end',async event=>{
    if(!active||event.willContinue)return;
    if(inflight)await inflight;
    await poll();
    const last=[...(event.messages||[])].reverse().find(m=>m.role==='assistant');
    elapsed=(performance.now()-started)/1000;active=false;
    phase=endPhase(last,toolErrors);render();
    context.ui.setWorkingMessage();
  });
  pi.on('session_shutdown',()=>{stopped=true;generation++;context?.ui.setWidget('tensorfold-live',undefined);});
  return {setPhase(value){if(active&&phase!==value){phase=value;context?.ui.setWorkingMessage(value);render();}}};
}
