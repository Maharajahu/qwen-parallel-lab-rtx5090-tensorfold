import assert from 'node:assert/strict';
import {test} from 'node:test';
import {LiveCodeFeed,branchRenderer} from './branch-view.mjs';

test('parallel source lines appear without waiting for earlier files',()=>{
  const feed=new LiveCodeFeed();
  feed.push('part0.js','```javascript\nfunction part0(ctx){');
  feed.push('part7.js','function part7(ctx){return 7;}\n');
  const before=feed.text;
  assert.equal(before,'part7.js │ function part7(ctx){return 7;}\n');
  feed.push('part0.js','return 0;}\n```');feed.finish('part0.js');
  assert.ok(feed.text.startsWith(before));
  assert.equal(feed.text,before+'part0.js │ function part0(ctx){return 0;}\n');
  assert.equal(feed.streams.get('part0.js').pending,'');
});
test('split chunks preserve source lines and flush unfinished final lines once',()=>{
  const feed=new LiveCodeFeed();
  feed.push('part2.js','```java');feed.push('part2.js','script\nconst x = "');
  feed.push('part1.js','const other = 1;\n');
  feed.push('part2.js','șir";\n\nreturn x;');
  feed.finish('part2.js');feed.finish('part2.js');
  assert.equal(feed.text,'part1.js │ const other = 1;\npart2.js │ const x = "șir";\npart2.js │ \npart2.js │ return x;\n');
  assert.equal(feed.snapshot().shownLines,4);
  assert.equal(feed.snapshot().streams['part2.js'].pending,0);
});
test('code presentation preserves literal source and has no twelve-line tail limit',()=>{
  const code=Array.from({length:60},(_,i)=>`const x${i} = ${i};`).join('\n');
  class Text {constructor(text){this.text=text}}
  const renderer=branchRenderer(Text),theme={fg:(_color,text)=>text};
  const result={content:[{type:'text',text:'8 files verified'}],details:{previewCode:code}};
  const partial=renderer.renderResult(result,{isPartial:true,expanded:false},theme).text;
  assert.ok(partial.includes('const x0 = 0;')&&partial.includes('const x59 = 59;'));
  assert.equal(renderer.renderResult(result,{isPartial:false,expanded:false},theme).text,'8 files verified');
  assert.ok(renderer.renderResult(result,{isPartial:false,expanded:true},theme).text.includes('8 files verified'));
  assert.doesNotMatch(renderer.renderCall({directory:'castle',prompt:'original prompt'}, {},theme).text,/original prompt|Args/);
});
