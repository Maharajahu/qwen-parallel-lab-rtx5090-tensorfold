"""Assemble twelve generated components using the preserved Three.js host and SDK."""
import base64, html, json, math, re, sys
from pathlib import Path
HOST = Path(__file__).resolve().parent
ROOT = HOST.parent.parent / 'fanout'
sys.path.insert(0, str(ROOT))
from fanout import syntax_check

def validate_plan(plan):
    if len(plan['parts']) != 12 or [p['id'] for p in plan['parts']] != list(range(12)):
        raise ValueError('Plan must contain exactly twelve components numbered 0..11')
    for field in ('title','subtitle','palette','camera','lookAt','layout','site'):
        if field not in plan:
            raise ValueError(f'Missing plan field {field}')
    vectors=[plan['camera'],plan['lookAt']]
    for part in plan['parts']:
        vectors.extend([part['origin'],part['size']])
        if not part['task'] or not part['name']:
            raise ValueError('Every component needs a name and task')
        if any(n <= 0 for n in part['size']):
            raise ValueError('Component size must be positive')
    for vector in vectors:
        if len(vector)!=3 or not all(type(n) in (int,float) and math.isfinite(n) for n in vector):
            raise ValueError('Plan vectors must have three finite numbers')

def assemble(plan, codes, output):
    template = (HOST / "page.html").read_text(encoding="utf-8")
    # A JSON string in a script element must not introduce an HTML closing tag.
    config = json.dumps(plan, ensure_ascii=False).replace("<", "\\u003c")
    # The component SDK exposes the documented API in each isolated closure.
    # Original generated code remains intact inside the closure.
    bindings = "THREE,scene,palette,state,addUpdate,registerAction,addHotspot,site,part,random,geometry,makeWater"
    source = "\n\n".join(f"const part{i} = (ctx) => {{ const {{{bindings}}} = ctx; return (\n{codes[i]}\n)(ctx); }};" for i in range(12))
    if re.search(r"</script", source, re.I):
        raise ValueError("Generated code contains a closing script tag")
    syntax_check(source, output / "generated.js")
    core = (ROOT / "vendor/three.core.min.js").read_bytes()
    module = (ROOT / "vendor/three.module.min.js").read_text(encoding="utf-8")
    if "./three.core.min.js" not in module:
        raise ValueError("Unexpected Three.js module layout")
    module = module.replace("./three.core.min.js", "three-core")
    data_url = lambda data: "data:text/javascript;base64," + base64.b64encode(data).decode()
    imports = json.dumps({"imports": {"three-core": data_url(core), "three": data_url(module.encode()),'three-reflector':data_url((ROOT/'vendor/Reflector.js').read_bytes())}})
    sdk=(ROOT/'geometry_sdk.mjs').read_text().replace('export function','function',1)
    water=(ROOT/'water.mjs').read_text().replace('export function','function',1)
    page = template.replace("__TITLE__", html.escape(plan["title"])).replace("__IMPORTMAP__", imports).replace("__CONFIG__", config).replace("__GEOMETRY_SDK__", sdk).replace('__WATER_SDK__',water).replace("__PARTS__", source)
    (output / "index.html").write_text(page, encoding="utf-8")
