import { spawn } from 'node:child_process';
import { readFileSync, existsSync, readdirSync, appendFileSync, writeFileSync, mkdirSync, realpathSync, statSync, openSync,readSync,closeSync } from 'node:fs';
import { resolve, dirname, relative, isAbsolute } from 'node:path';
import { fileURLToPath } from 'node:url';
import { StringDecoder } from 'node:string_decoder';
import { attachLiveStatus } from './live-status.ts';
import { LiveCodeFeed, sceneRenderer } from './scene-view.ts';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');

export function workPath(cwd, name) {
  if (!name || isAbsolute(name)) throw new Error('Use a relative workspace path.');
  const base=realpathSync(cwd), result=resolve(base,name), rel=relative(base,result);
  if (rel==='..' || rel.startsWith('..\\') || rel.startsWith('../') || isAbsolute(rel)) throw new Error('Path leaves the workspace.');
  let ancestor=result;while(!existsSync(ancestor)) ancestor=dirname(ancestor);
  const actual=relative(base,realpathSync(ancestor));
  if(actual==='..'||actual.startsWith('..\\')||actual.startsWith('../')||isAbsolute(actual)) throw new Error('Link leaves the workspace.');
  return result;
}

export function workspaceFile(cwd, p) {
  const path=workPath(cwd,p.path);
  if(p.action==='read') {
    if(statSync(path).isDirectory()) return readdirSync(path).slice(0,40).join('\n');
    const lines=readFileSync(path,'utf8').split('\n'),start=Math.max(0,(p.line||1)-1);
    const result=lines.slice(start,start+30).map((line,i)=>`${start+i+1}: ${line}`).join('\n');
    return result.slice(0,2600)+(result.length>2600?'\n[truncated at 2600 characters]':`\n[${lines.length} total lines]`);
  }
  if(typeof p.content!=='string') throw new Error('content is required for writes and replacements.');
  if(p.action==='write') {
    if(existsSync(path)) throw new Error('File exists. Use replace with an exact, unique old text.');
    mkdirSync(dirname(path),{recursive:true});writeFileSync(path,p.content,{encoding:'utf8',flag:'wx'});
  } else if(p.action==='replace') {
    if(!p.old)throw new Error('old must be nonempty.');
    const before=readFileSync(path,'utf8');
    if(before.split(p.old).length!==2)throw new Error('old must occur exactly once; read the file first.');
    writeFileSync(path,before.replace(p.old,()=>p.content),'utf8');
  } else throw new Error('Unknown file action.');
  return `Saved ${p.path}; ${statSync(path).size} bytes.`;
}

export default async function (pi) {
  const {Text}=await import('@oh-my-pi/pi-tui');
  const z = pi.zod;
  const liveStatus=attachLiveStatus(pi);
  pi.setLabel('TensorFold local scene builder');
  pi.on('before_provider_request', async (event,ctx) => {
    if(ctx.model?.provider!=='TensorFold-Local')return;
    const payload=event.payload;
    const response=await fetch('http://127.0.0.1:18190/tokenize',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({...payload,add_generation_prompt:true}),signal:AbortSignal.timeout(10000)});
    if(!response.ok)throw new Error(`Local token preflight failed: ${response.status} ${await response.text()}`);
    const info=await response.json(),available=info.max_model_len-info.count-128;
    if(available<128)throw new Error(`Context length leaves only ${available} output tokens. Compact this conversation before continuing.`);
    const max_tokens=Math.min(payload.max_tokens||1024,available);
    if(process.env.OMP_CAPTURE_EVENTS)appendFileSync(process.env.OMP_CAPTURE_EVENTS,JSON.stringify({time:Date.now(),type:'request_preflight',prompt_tokens:info.count,max_tokens})+'\n');
    return {...payload,max_tokens};
  });
  if (process.env.OMP_CAPTURE_EVENTS) {
    for (const type of ['agent_start','agent_end','tool_call','tool_result']) {
      pi.on(type, event => { appendFileSync(process.env.OMP_CAPTURE_EVENTS, JSON.stringify({time:Date.now(),type,event})+'\n'); });
    }
  }
  pi.registerTool({
    name:'workspace_file',label:'Workspace file',loadMode:'essential',
    description:'Read a file (30 lines, max 2600 chars; optional starting line) or list a directory. Write a NEW file. Replace one exact unique old string in an existing file. Paths stay inside the working directory.',
    parameters:z.object({action:z.enum(['read','write','replace']),path:z.string(),content:z.string().optional(),old:z.string().optional(),line:z.number().int().min(1).optional()}),
    async execute(_id,p,_signal,_update,ctx){return {content:[{type:'text',text:workspaceFile(ctx.cwd,p)}],details:{path:p.path,action:p.action}};}
  });
  pi.registerTool({
    name:'repair_scene',label:'Repair scene components',loadMode:'essential',
    description:'Repair failed scene components in a new output directory, preserving other components. feedback maps component numbers 0-7 to specific errors. Revalidates and assembles the HTML.',
    parameters:z.object({source:z.string(),directory:z.string().regex(/^[a-zA-Z0-9_-]+$/),feedback:z.record(z.string(),z.string())}),
    async execute(_id,p,signal,update,ctx){
      const source=workPath(ctx.cwd,p.source),destination=workPath(ctx.cwd,p.directory);
      if(existsSync(destination))throw new Error('Output already exists.');
      const feedback=resolve(ctx.cwd,`.repair-${Date.now()}.json`);writeFileSync(feedback,JSON.stringify(p.feedback));
      const result=await new Promise((accept,reject)=>{
        const child=spawn(process.env.FANOUT_PYTHON||'python',[resolve(root,'fanout.py'),'--repair-from',source,'--feedback',feedback,'--output',destination,'--contract','compact'],{cwd:root,windowsHide:true});
        let output='';const cancel=()=>child.kill();signal?.addEventListener('abort',cancel,{once:true});
        child.stdout.on('data',b=>{output+=b.toString();update?.({content:[{type:'text',text:output.slice(-700)}]});});child.stderr.on('data',b=>{output+=b.toString()});
        child.on('error',reject);child.on('close',code=>{signal?.removeEventListener('abort',cancel);accept({code,output})});if(signal?.aborted)cancel();
      });
      const summary=existsSync(resolve(destination,'summary.json'))?JSON.parse(readFileSync(resolve(destination,'summary.json'),'utf8')):null;
      if(result.code!==0)throw new Error(JSON.stringify(summary?.failures||result.output.slice(-1000)));
      return {content:[{type:'text',text:`Repaired components ${Object.keys(p.feedback).join(', ')}. Created ${p.directory}/index.html. All 8 components validated; browser inspection still required.`}],details:{summary}};
    }
  });
  pi.registerTool({
    name: 'build_scene', label: 'Build 3D scene', loadMode: 'essential',
    ...sceneRenderer(Text),
    description: 'Build a Gothic castle / fantasy Three.js website from the EXACT original user prompt. Fresh local plan, eight parallel GPU code streams, validated HTML assembly. Returns real files and measured aggregate generation throughput. Specialized scene builder; use workspace_file for general coding.',
    parameters: z.object({prompt: z.string().min(1), directory: z.string().regex(/^[a-zA-Z0-9_-]+$/).describe('New subdirectory in the working directory; never overwrite an existing build')}),
    async execute(_id, params, signal, update, ctx) {
      const destination = resolve(ctx.cwd, params.directory);
      if (existsSync(destination)) throw new Error('Output directory already exists; choose a new name.');
      const start = performance.now();
      let stdout = '', stderr = '';
      const progress=new Map();
      const feed=new LiveCodeFeed();
      const displayLog=process.env.OMP_CAPTURE_EVENTS?resolve(dirname(process.env.OMP_CAPTURE_EVENTS),'stream-display.jsonl'):null;
      let previewCode='',lastDisplay='';
      const result = await new Promise((accept, reject) => {
        const child = spawn(process.env.FANOUT_PYTHON || 'python', [resolve(root, 'fanout.py'), '--prompt', params.prompt,
          '--output', destination, '--contract', 'compact', '--request-order', '3,2,6,7,4,1,0,5', '--live-status'],
          {cwd: root, windowsHide: true, stdio: ['ignore','pipe','pipe']});
        let settled = false;
        const cancel = () => child.kill();
        signal?.addEventListener('abort', cancel, {once:true});
        const refresh = () => {
          try {
            const files = existsSync(destination) ? readdirSync(destination) : [];
            const finished = files.filter(f => /^part\d\.js$/.test(f)).length;
            const streams = files.filter(f => /^part\d\.events\.jsonl$/.test(f));
            const received=[];
            for (const file of streams) {
              const path=resolve(destination,file),size=statSync(path).size;
              let state=progress.get(file);
              if(!state){state={offset:0,pending:'',decoder:new StringDecoder('utf8')};progress.set(file,state)}
              if(size>state.offset){
                const fd=openSync(path,'r');
                try{const buffer=Buffer.allocUnsafe(size-state.offset),count=readSync(fd,buffer,0,buffer.length,state.offset);state.offset+=count;state.pending+=state.decoder.write(buffer.subarray(0,count));}
                finally{closeSync(fd)}
              }
              const rows=state.pending.split('\n');state.pending=rows.pop();
              for (const row of rows) {
                if(!row.trim())continue;
                const event = JSON.parse(row);
                for(const c of event.event?.choices||[])received.push({file:file.replace('.events.jsonl','.js'),
                  text:c.delta?.content||'',done:!!c.finish_reason,time:event.received_at_ms});
              }
            }
            received.sort((a,b)=>(a.time||0)-(b.time||0));
            for(const item of received){feed.push(item.file,item.text);if(item.done)feed.finish(item.file);}
            liveStatus.setPhase(streams.length?(finished===8?'Assembling':`Generating ${finished}/8`):'Planning');
            previewCode=feed.text;
            const status=streams.length?`Generating ${finished}/8 files`:'Planning with local Qwen3.8 27B…';
            const display=previewCode+'\n'+status;
            if(display!==lastDisplay) {
              lastDisplay=display;
              update?.({content:[{type:'text',text:status}],details:{previewCode,elapsed:(performance.now()-start)/1000,finished,chars:feed.received}});
              if(displayLog)appendFileSync(displayLog,JSON.stringify({time:Date.now(),...feed.snapshot(),
                eventLagMs:received.filter(item=>item.text&&Number.isFinite(item.time)).map(item=>Date.now()-item.time)})+'\n');
            }
          } catch (error) { stderr += `\nProgress read: ${error.message}`; }
        };
        const ticker = setInterval(refresh,33);
        const finish = (error, code) => {
          if (settled) return; settled = true; clearInterval(ticker);refresh();
          signal?.removeEventListener('abort',cancel);
          if (error) reject(error); else accept(code);
        };
        child.stdout.on('data', b => {stdout += b.toString();});
        child.stderr.on('data', b => {stderr += b.toString();});
        child.on('error', error => finish(error,null));
        child.on('close', code => finish(null,code));
        if(signal?.aborted) cancel();
      });
      if(result !== 0) {
        const failed=existsSync(resolve(destination,'summary.json'))?JSON.parse(readFileSync(resolve(destination,'summary.json'),'utf8')):null;
        throw new Error(`Build failed in ${params.directory}. Use repair_scene for these component errors: ${JSON.stringify(failed?.failures||stderr.slice(-1000))}`);
      }
      const summary = JSON.parse(readFileSync(resolve(destination,'summary.json'),'utf8'));
      const plan = JSON.parse(readFileSync(resolve(destination,'plan.json'),'utf8'));
      if(summary.failures.length || summary.sections_valid !== 8) throw new Error('Incomplete scene; inspect summary.json.');
      for(const file of feed.streams.keys())feed.finish(file);
      previewCode=feed.text;
      liveStatus.setPhase('Browser check');
      update?.({content:[{type:'text',text:`8/8 components validated · ${summary.generation_aggregate_tps.toFixed(2)} tokens/s aggregate\nChecking the rendered scene and camera controls…`}],details:{previewCode}});
      const preview=await pi.exec(process.env.FANOUT_PYTHON||'python',[resolve(root,'omp-agent/inspect_scene.py'),destination],{signal,timeout:45000});
      if(preview.code!==0)throw new Error(`Browser validation failed: ${preview.stderr.slice(-1200)}`);
      const browser=JSON.parse(preview.stdout.trim());
      const text = `Created ${params.directory}/index.html — ${plan.title}\n8/8 JavaScript components validated. ${summary.generated_completion_tokens} tokens in ${summary.generation_seconds.toFixed(2)} s: ${summary.generation_aggregate_tps.toFixed(2)} tokens/s aggregate.\nFresh planning + generation + assembly: ${summary.artifact_seconds.toFixed(2)} s; browser verification: ${browser.seconds.toFixed(2)} s.\nBrowser rendered all 8 components with zero errors. Orbit drag and scroll zoom exercised. Controls: ${browser.buttons.join(', ')}.\nScreenshot and receipt: ${params.directory}/browser-preview.png and browser-receipt.json. Open index.html in a modern browser. Report completion; no need to reread these large generated files unless the user requests a change.`;
      return {content:[{type:'text',text}],details:{directory:destination,summary,browser,previewCode}};
    }
  });
}
