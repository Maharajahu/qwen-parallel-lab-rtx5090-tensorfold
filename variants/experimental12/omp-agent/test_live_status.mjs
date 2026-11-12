import assert from 'node:assert/strict';
import {test} from 'node:test';
import {LiveMeter,statusText,endPhase} from './live-status.mjs';

test('a completed agent turn retains tool error evidence without reporting a fatal agent error',()=>{
  assert.equal(endPhase({stopReason:'stop'},0),'Done');
  assert.equal(endPhase({stopReason:'stop'},1),'Done · 1 tool error observed');
  assert.equal(endPhase({stopReason:'error'},0),'Error');
  assert.equal(endPhase({stopReason:'aborted'},1),'Stopped');
});

const load=(decode,prefill=0,running=8,instance='one',prefillUs=prefill*250)=>({model:'qwen27-sync-speed',instance,parked:false,lanes:8,running,waiting:0,tokens:{decode,prefill_compute:prefill},busy_us:{prefill:prefillUs}});
test('live output rate comes from committed native tokens, across completed streams',()=>{
  const m=new LiveMeter();m.sample(load(100),0);
  m.sample(load(275,1000),250);
  assert.equal(m.latest.rate,700);assert.equal(m.latest.decoded,175);assert.equal(m.latest.prefillRate,4000);
  m.sample(load(450,1000,5),500);
  assert.equal(m.latest.rate,700);assert.equal(m.latest.decoded,350);
  m.sample(load(800,1000,0),1000);
  assert.equal(m.latest.rate,0);assert.equal(m.latest.decoded,700);
});
test('rolling window forgets old fast output without changing total tokens',()=>{
  const m=new LiveMeter();for(let n=0;n<=4;n++)m.sample(load(n*175),n*250);
  for(let n=5;n<=8;n++)m.sample(load(700+(n-4)*25),n*250);
  assert.equal(m.latest.rate,100);assert.equal(m.latest.decoded,800);
});
test('restart and counter regression rebase instead of displaying negative or spiked rates',()=>{
  const m=new LiveMeter();m.sample(load(500),0);m.sample(load(900),500);
  m.sample(load(4,0,1,'two'),1000);
  assert.equal(m.latest.rate,0);assert.equal(m.latest.decoded,0);assert.equal(m.latest.reset,true);
  m.sample(load(2,0,1,'two'),1250);assert.equal(m.latest.decoded,0);assert.equal(m.latest.reset,true);
});
test('missing or disconnected telemetry is unavailable, never an invented rate',()=>{
  const m=new LiveMeter();assert.throws(()=>m.sample({model:'qwen27-sync-speed'},0));
  m.sample(load(0),0);m.sample(load(700),1000);m.unavailable();
  assert.match(statusText(m,'Generating',1.5,true),/telemetry unavailable/);
  assert.doesNotMatch(statusText(m,'Generating',1.5,true),/700/);
});
test('completed turn keeps its decoded count and zero live speed',()=>{
  const m=new LiveMeter();m.sample(load(0),0);m.sample(load(700),1000);
  const text=statusText(m,'Done',2,false);
  assert.match(text,/decode 0\.0 tok\/s · 700 tok/);assert.match(text,/2\.0 s \| Done/);
});
test('prefill uses native compute time, excludes prior turns and survives decode and idle',()=>{
  const m=new LiveMeter();m.sample(load(500,2000,0,'one',1000000),0);
  m.sample(load(510,3000,1,'one',1250000),500);
  assert.equal(m.latest.prefilled,1000);assert.equal(m.latest.prefillSeconds,.25);assert.equal(m.latest.prefillRate,4000);
  m.sample(load(650,3000,1,'one',1250000),1500);
  m.sample(load(700,3000,0,'one',1250000),2500);
  const text=statusText(m,'Done',2.5,false);
  assert.match(text,/prefill avg 4,000 tok\/s · 1,000 tok · 0\.25 s/);
  assert.match(text,/decode 0\.0 tok\/s · 200 tok/);
});
test('missing prefill timing is unavailable; zero time never fabricates a speed',()=>{
  const m=new LiveMeter(),missing=load(0);delete missing.busy_us;
  assert.throws(()=>m.sample(missing,0));
  m.sample(load(0),0);m.sample(load(20,100,1,'one',0),250);
  assert.equal(m.latest.prefillRate,null);assert.match(statusText(m,'Agent',.25,true),/prefill avg — tok\/s/);
});
test('a prefill clock reset rebases all counters',()=>{
  const m=new LiveMeter();m.sample(load(0,100,1,'one',10000),0);
  m.sample(load(100,1000,1,'one',1),250);
  assert.equal(m.latest.reset,true);assert.equal(m.latest.prefilled,0);assert.equal(m.latest.prefillSeconds,0);
});
test('a transient telemetry gap preserves totals and restarts only the live-rate window',()=>{
  const m=new LiveMeter();m.sample(load(100,100),0);m.sample(load(800,1100),1000);
  m.unavailable();m.sample(load(1500,2100),3000);
  assert.equal(m.latest.decoded,1400);assert.equal(m.latest.prefilled,2000);assert.equal(m.latest.rate,0);
  m.sample(load(1675,2100),3250);assert.equal(m.latest.rate,700);
  m.unavailable();m.sample(load(50,50),3500);assert.equal(m.latest.reset,true);assert.equal(m.latest.decoded,0);
});
