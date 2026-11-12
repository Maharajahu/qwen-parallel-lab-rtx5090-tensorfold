import { readFileSync } from 'node:fs';
import { Linter } from './lint/node_modules/eslint/lib/api.js';

const globals = Object.fromEntries([
  'THREE','scene','camera','renderer','ui','palette','state','addUpdate','registerAction','addHotspot','site','part','random','geometry','makeWater',
  'document','window','console','performance','innerWidth','innerHeight','devicePixelRatio',
  'requestAnimationFrame','cancelAnimationFrame','setTimeout','clearTimeout','setInterval','clearInterval'
].map(name => [name, 'readonly']));
const component=process.argv[3]===undefined?null:Number(process.argv[3]);
const restricted=[];
if(component===4)restricted.push({selector:"NewExpression[callee.object.name='THREE'][callee.property.name=/^(Circle|Plane)Geometry$/]",message:'Terrain already has its matching closed cap from solidRings. Remove the extra flat cap geometry entirely.'});
if(component!==null&&component!==7)restricted.push({selector:"CallExpression[callee.name='registerAction']",message:'Only component 7 owns the scene action. Other components must not create UI buttons.'});
const messages = new Linter().verify(readFileSync(process.argv[2], 'utf8'), {
  languageOptions: { ecmaVersion: 2022, sourceType: 'script', globals },
  rules: { 'no-undef': 'error', ...(restricted.length?{'no-restricted-syntax':['error',...restricted]}:{}), 'no-restricted-properties': ['error',
    {object:'scene',property:'fog',message:'Fog belongs to the host renderer.'},
    {object:'scene',property:'background',message:'Background belongs to the host renderer.'},
    {object:'Math',property:'random',message:'Use seeded ctx.random() for reproducible geometry.'}
  ] }
});
if (messages.length) {
  process.stderr.write(messages.map(m => `${m.line}:${m.column} ${m.ruleId || 'syntax'} ${m.message}`).join('\n'));
  process.exitCode = 1;
}
