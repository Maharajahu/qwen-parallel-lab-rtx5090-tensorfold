import assert from 'node:assert/strict';
import {test,after} from 'node:test';
import {mkdtempSync,readFileSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {workspaceFile,workPath} from './fanout-extension.ts';
const root=mkdtempSync(join(tmpdir(),'tensorfold-file-tests-'));
after(()=>rmSync(root,{recursive:true,force:true}));
test('write, read, exact replace preserve literal replacement characters',()=>{
  workspaceFile(root,{action:'write',path:'nested/a.txt',content:'hello\nworld'});
  assert.match(workspaceFile(root,{action:'read',path:'nested/a.txt'}),/1: hello/);
  workspaceFile(root,{action:'replace',path:'nested/a.txt',old:'hello',content:'$& $`'});
  assert.equal(readFileSync(join(root,'nested/a.txt'),'utf8'),'$& $`\nworld');
});
test('reject overwrite and missing or nonunique replacement',()=>{
  workspaceFile(root,{action:'write',path:'b.txt',content:'xx xx'});
  assert.throws(()=>workspaceFile(root,{action:'write',path:'b.txt',content:'new'}),/exists/);
  assert.throws(()=>workspaceFile(root,{action:'replace',path:'b.txt',old:'xx',content:'z'}),/exactly once/);
  assert.throws(()=>workspaceFile(root,{action:'replace',path:'b.txt',old:'nope',content:'z'}),/exactly once/);
  assert.equal(readFileSync(join(root,'b.txt'),'utf8'),'xx xx');
});
test('reject workspace traversal and absolute paths',()=>{
  for(const path of ['../escape.txt','..\\escape.txt','C:\\Windows\\win.ini'])assert.throws(()=>workPath(root,path));
});
test('bound long reads and support line pagination',()=>{
  writeFileSync(join(root,'long.txt'),'z'.repeat(9000)+'\nsecond');
  const result=workspaceFile(root,{action:'read',path:'long.txt'});
  assert.ok(result.length<2700);assert.match(result,/truncated/);
  assert.match(workspaceFile(root,{action:'read',path:'long.txt',line:2}),/2: second/);
});
