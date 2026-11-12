"""One prompt -> local plan -> eight parallel code sections -> one HTML artifact."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Event
import html
import json
import math
from pathlib import Path
import re
import subprocess
import time

from client import complete

ROOT = Path(__file__).resolve().parent
DEFAULT_PROMPT = "build me a html three.js website for harry potter, it should be a masterpiece."
CONTRACT = """
The host creates Three.js THREE, scene, PerspectiveCamera, WebGLRenderer, baseline
hemisphere/moon lighting and interactive orbit/zoom controls. The host owns resize
and animation. World Y is up. Each section exports exactly ONE plain
function partN(ctx). All declarations stay INSIDE it. No imports, async, scripts,
renderer.render, requestAnimationFrame, new camera/renderer, external assets,
network calls, persistent timers, alert, or accesses to another section's local variables.
ctx contains {THREE, scene, palette, state, addUpdate, registerAction, addHotspot,
site, part, random, geometry, makeWater}. scene is YOUR OWN THREE.Group, positioned at part.origin by
the host. ALL coordinates you create are LOCAL to that origin. Do not add the
origin again. site contains shared world measurements; part contains your footprint.
random() is a deterministic seeded random generator. Use it instead of Math.random.
The host also makes these names available in your
function's enclosing scope, so both ctx.addUpdate and addUpdate are valid.
palette is the plan's hex colour dictionary. state has paused, time, selected.
addUpdate(fn) registers fn(deltaSeconds, elapsedSeconds); host calls it when playing.
registerAction(label, fn) adds an accessible button; fn runs on click.
addHotspot(mesh, title, description) registers a pickable THREE mesh, no callbacks.
No DOM/UI, camera, renderer, lighting, fog or background changes. No light objects.
The host owns presentation. Only the MAGIC component (id7) may use registerAction,
for a single meaningful 'Lumos' effect. All other parts add NO buttons.
Respect the exact local footprint and origin. Build connected, believable geometry:
primary silhouette, secondary structures, then repeated small details. Buildings
must have multi-storey rhythm, roof ridges/spires, stone bands, buttresses and many
visible warm windows on ALL visible exterior sides. Place glass OUTSIDE the wall
surface and IN FRONT of its frame, never hidden inside opaque geometry. Windows
should use emissive amber with dark mullions. Roofs are slate, stone is lighter.
Architecture is richly detailed storybook Gothic, not a few bare boxes and cones.
Never use an oversized opaque plane/sphere in front of the castle. Trees stay low
and outside the clear foreground viewing sector. Terrain must meet building bases.
Use current Three.js APIs, MeshStandardMaterial, BufferGeometry, THREE.MathUtils.
Use procedural geometry, shared geometries/materials and instancing for repeats.
Keep geometry count reasonable. Avoid using Math.random in animation callbacks.
For every Group use .add(object), for scene objects use scene.add(object).
Your local helper functions may build arches, gables, window rows and buttresses.
Use the host's correct reusable primitives instead of constructing roof planes:
geometry.gable(width,depth,rise,roofMaterial,wallMaterial) returns a CLOSED roof
mesh, eaves centered at local y=0; ridge runs along Z. Set its position to wall top.
Gable roofs belong to rectangular halls only. Round tower spires MUST use
THREE.ConeGeometry(radius,height,24), positioned with cone base on shaft top.
geometry.arch(width,height,depth,thickness,material) returns a pointed OPEN arch,
base at y=0, width along X, depth along Z. It contains no opaque filling.
geometry.window(width,height,frameMaterial,glassMaterial) returns a Gothic window
group with frame/mullions and visible glass, base at y=0, facing +Z. Mount .15 units
outside a wall; rotate y for other wall directions. Use these for all gables,
arches and windows; still create varied shafts, ledges, roofs, dormers, buttresses,
stairways, chimneys and tracery with your own loops and scene composition.
geometry.solidRings(rings,sideMaterial,capMaterial) returns a CLOSED irregular
solid, including correctly facing side faces and matching end caps. Each ring is
an array of [x,y,z] at angles 0..2pi (x=cos,z=sin); rings are ordered BOTTOM to TOP
with equal vertex counts. For terrain create 48-64 vertices per ring, 3-4 layers,
continuous rough radius variations and use this helper, not custom triangle indices.
Do not add a separate flat cap; the solid includes its matching top. Positions are
local; keep ground y=0 in a terrain group whose world origin is at site.baseY.
THREE.PointsMaterial has color, size, opacity but NO emissive property.
The WATER component must use makeWater(800), which returns a horizontal lake at
LOCAL y=0 with REAL planar reflection and animated subtle ripples. Add it to scene.
Do not create another water plane, bright reflection strips or large ripple rings.
Landscape mountains are distant tapered cone/rock silhouettes, ONLY at world
z <= -200, height 15..45; never create giant cylindrical flat-topped walls.
Create geometry, do not spend output on comments or prose. No JSON, markdown,
placeholder TODOs, empty helpers, or unfinished features. Fully close the function.
""".strip()


def clean_code(text):
    text = text.strip()
    if text.startswith("```"):
        first, separator, rest = text.partition("\n")
        if separator and first.strip().lower() in ("```", "```js", "```javascript", "```json", "```typescript", "```html"):
            text = rest
        else:
            text = text[3:].lstrip()
        if text.endswith("```"):
            text = text[:-3].rstrip()
    return text


def syntax_check(code, path, component_id=None):
    path.write_text(code, encoding="utf-8")
    command=["node", str(ROOT / "lint_component.mjs"), str(path)]
    if component_id is not None:command.append(str(component_id))
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise ValueError(result.stderr)


def validate_plan(plan):
    if len(plan['parts']) != 8 or [p['id'] for p in plan['parts']] != list(range(8)):
        raise ValueError('Plan must contain exactly eight components numbered 0..7')
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


def make_plan(prompt, output):
    instruction = """Act as an architectural art director for an interactive Three.js scene.
Return ONLY a JSON object: title (short), subtitle (short), palette (object with
stone, roof, gold, water, foliage, sky as #rrggbb strings), camera ([x,y,z]),
lookAt ([x,y,z]), layout (short visual composition), site (shared dimensions:
baseY, waterY, plateauWidth, plateauDepth), parts (EXACTLY 8 objects with id 0..7,
name, origin [x,y,z] IN WORLD SPACE, size [width,height,depth], task).
Make ONE coherent Hogwarts-inspired castle complex on a rocky island above a lake.
Architectural bases y=12, water y=-2, plateau 60 wide x 56 deep. Castle footprint
roughly x[-24,24],z[-20,22]. Back is negative Z, front positive Z. Elevated camera
[72,48,88] looks at [0,23,0]. Keep the foreground lake and castle facade visible.
Four of eight tasks make adjoining architecture with exact local sizes/origins:
0 long central great hall width14 depth28 bodyheight13 roofrise7, using geometry.gable,
rows of exterior Gothic windows, buttresses, chimneys; 1 four connected cylindrical
towers/spires, main shaft diameter7 height27 plus spire12, others smaller, with tiered shafts, ledges,
window bands and smaller turrets; 2 east school wing with rows of roof dormers and
arcades; 3 front courtyard/bridge, cloisters and vaulted arches. Ensure connections
through touching footprints and the same base height. Main tower up to 45 above base.
4 island and cliffs: solid irregular rounded rock island supports every building,
ground exactly y12, rock down to water y-2, ellipse radii42 and38. Continuous
connected rocky sides with cracks/boulders, dark earth cap, NO square slab or
separate perimeter columns. Trees only BEHIND and to sides, height max7, no
foreground tree ring. 5 water and distant landscape: 800x800 lake y-2 reaching
horizon, distant irregular mountain ridges at world z=-180 and beyond, reflected
warm streaks and subtle ripples; avoid exposed plane edges. 6 sky: a SINGLE
inward sphere radius650 around origin, smooth blue-hour gradient via ShaderMaterial,
sparse tiny stars, distant moon behind castle. NO panels/stacked planes or bands.
7 magic: animated tiny golden flying motif/trails and a few glowing floating candles
around courtyard; don't obscure architecture. At least three physical landmarks
have hotspots, created by their architecture owners.
Use lighter warm grey limestone (#9c9589 range), dark slate-blue roofs, amber windows,
dark slate/earth for terrain (NOT the limestone wall color),
desaturated teal water, navy-blue sky. Readable enchanted blue-hour illumination,
not black nighttime silhouettes. No external assets. The host owns lighting,
fog, camera, UI, animation loop and orbit controls. Don't assign those as parts.
Each task needs 60-100 words specifying geometry, counts of repeated details,
footprint, materials, local coordinates and integration edges. Each section gets
its OWN group translated to its origin; task geometry must use LOCAL coordinates.
In task prose every building base is LOCAL y=0, terrain top is LOCAL y=0 with
rocks extending DOWN to y=-14, and water is LOCAL y=0. NEVER repeat world origin
heights as local geometry coordinates. Size includes roofs and spires.
Other part names/origins/sizes are shared for context, but code is independent.
Plan at most 1700 tokens. Return complete JSON only."""
    messages=[{"role":"system","content":instruction},{"role":"user","content":prompt}]
    initial=None
    for attempt in range(2):
        text,receipt=complete(messages,output/('plan' if attempt==0 else 'plan-repair'),2200)
        try:
            if receipt['finish_reason']!='stop':
                raise ValueError('Plan exceeded its output budget; keep it under 1700 tokens')
            plan=json.loads(clean_code(text))
            validate_plan(plan)
            break
        except (ValueError,KeyError,TypeError) as error:
            if attempt:
                raise
            initial=receipt
            messages[-1]['content']=prompt+'\nPrevious plan rejected: '+str(error)[:250]+'. Produce strictly valid complete JSON. IDs are integers; quote string values correctly.'
    if initial:
        receipt['initial_attempt']=initial
    (output / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan, receipt


def compact_contract(number):
    common = f"""Output complete JavaScript function part{number}(ctx), ~1800 tokens, no comments/prose.
ctx and enclosing scope provide THREE,scene,palette,state,site,part,random,geometry,
makeWater,addUpdate,registerAction,addHotspot. scene is YOUR Group at part.origin:
LOCAL coordinates only, respecting part.size. Neighbors are boundaries, not tasks.
Host owns camera,renderer,lights,fog,background,DOM/UI,animation. Do not modify them.
No imports,async,network,assets,timers,globals,other parts' locals or placeholders.
Current Three.js; shared geometry/materials, palette and seeded random(), no Math.random.
addUpdate(fn): fn(deltaSeconds,elapsedSeconds). addHotspot(mesh,title,description):
selectable mesh, no callback. Only part7 uses registerAction(label,fn), one Lumos.
All declarations inside function; scene.add(object); fully close every brace.
"""
    if number < 4:
        return common + """Build richly detailed connected Gothic architecture: strong silhouette, many
visible exterior warm windows, stone bands, buttresses, roof detail and small turrets.
Use these tested primitives:
geometry.gable(width,depth,rise,roofMaterial,wallMaterial): CLOSED roof, eaves y=0,
ridge along Z. Place at wall top. Rectangular halls only; round spires use
ConeGeometry(radius,height,24), base on shaft top.
geometry.arch(width,height,depth,thickness,material): OPEN pointed arch, base y=0,
width X/depth Z. geometry.window(width,height,frameMaterial,glassMaterial): Gothic
frame+mullions+glass, base y=0, facing +Z. Mount .15 outside wall and rotate y for
other sides. Warm emissive glass must remain visible. Add a landmark hotspot.
"""
    if number == 4:
        return common + """Use geometry.solidRings(rings,sideMaterial,capMaterial) for the CLOSED island.
Each ring has 48-64 [x,y,z] vertices, angle 0..2pi (x=cos,z=sin); equal counts,
3-4 rings ordered BOTTOM to TOP. Continuous irregular radii; no separate cap,
planes, columns or gaps. Top LOCAL y=0, bottom -14; supports all architecture.
Use dark earth/rock, cracks and small boulders. Low trees behind/to sides only.
"""
    if number == 5:
        return common + """This section contains ONLY the lake and distant mountains, in under 900 tokens.
Use scene.add(makeWater(800)) for the lake at LOCAL y=0; factory already
includes real planar reflection and animated subtle ripples. No extra water planes,
reflection strips or ripple rings. Distant mountains: tapered irregular silhouettes
ONLY world z<=-200, heights15..45. No giant cylinders or foreground obstructions.
Use one loop for five overlapping ridges of varied ConeGeometry meshes. Do not add
moon, stars, trees, boats, bridges, rocks near the island, UI or hotspots: other
components own them. Ignore the plan's fake reflected streaks; makeWater handles reflection.
Use solid cones with varied rotations/scales, NOT per-vertex jitter (it tears seams).
Mountains use dark navy MeshBasicMaterial color '#1b2939', not limestone.
"""
    if number == 6:
        return common + """Sky: unscaled SphereGeometry(650) with ShaderMaterial side:THREE.BackSide,
depthWrite:false and smooth navy-blue-hour gradient. Never invert/scale geometry.
Sparse tiny stars; one small moon radius5 at local [0,120,-400], without halo spheres.
No stacked planes, bands or global changes. PointsMaterial has NO emissive property.
"""
    return common + """Tiny golden flying motif and subtle trails/candles around courtyard.
Use addUpdate for motion; keep architecture visible. One meaningful Lumos button.
PointsMaterial has color,size,opacity but NO emissive property. No light objects.
"""


def generate_part(plan, part, prompt, output, max_tokens, review=None, contract="full", admission=None):
    number = part["id"]
    instruction = compact_contract(number) if contract == "compact" else CONTRACT.replace("partN", f"part{number}")
    shared = {k:plan[k] for k in ('palette','site','layout')}
    shared["neighbors_id_origin_size"] = [[p['id'],p['origin'],p['size']] for p in plan["parts"] if p['id'] != number]
    if contract == 'compact':
        task = f"USER REQUEST: {prompt}\nSHARED: {json.dumps(shared,separators=(',',':'))}\nYOUR SECTION: {json.dumps(part,separators=(',',':'))}\nUse reusable local helpers and loops for rich visible detail. Finish within budget."
    else:
        task = f"USER REQUEST: {prompt}\nSHARED PLAN: {json.dumps(shared)}\nYOUR SECTION: {json.dumps(part)}\nWrite function part{number}(ctx) only. Budget about 1800 tokens. Use compact reusable local helpers and loops to create rich visible detail. No comments. Finish completely within the budget."
    if review:
        task+='\nOBSERVED VISUAL/INTEGRATION DEFECTS TO CORRECT: '+review
    messages = [{"role": "system", "content": instruction}, {"role": "user", "content": task}]
    initial = None
    for attempt in range(2):
        target = output / (f"part{number}" if attempt == 0 else f"repairs/part{number}")
        try:
            text, receipt = complete(messages, target, max_tokens, admission=admission)
            code = clean_code(text)
            if receipt["finish_reason"] != "stop":
                raise ValueError("The function was cut off by the output token limit.")
            if not re.match(rf"^function\s+part{number}\s*\(\s*ctx\s*\)", code):
                raise ValueError("The output did not start with the required function signature.")
            syntax_check(code, output / f"part{number}.js",number)
            break
        except (ValueError, RuntimeError) as error:
            if isinstance(error,RuntimeError):
                if 'QwenContextFull' not in str(error):
                    raise
                receipt=json.loads(target.with_suffix('.failure.json').read_text())
            if attempt == 1:
                raise
            initial = receipt
            messages = [{"role": "system", "content": instruction}, {"role": "user", "content": task +
                        f"\nVALIDATION FAILED: {str(error)[:350]}\nRegenerate a COMPLETE compact implementation in at most 1800 tokens. Keep architectural silhouette and exterior details; remove lengthy comments. Close all braces."}]
    if initial:
        receipt["initial_attempt"] = initial
    print(json.dumps({"part": number, "tokens": receipt["usage"].get("completion_tokens"),
                      "seconds": round(receipt["elapsed_seconds"], 2)}), flush=True)
    return number, code, receipt


def assemble(plan, codes, output):
    template = (ROOT / "page.html").read_text(encoding="utf-8")
    # A JSON string in a script element must not introduce an HTML closing tag.
    config = json.dumps(plan, ensure_ascii=False).replace("<", "\\u003c")
    # The component SDK exposes the documented API in each isolated closure.
    # Original generated code remains intact inside the closure.
    bindings = "THREE,scene,palette,state,addUpdate,registerAction,addHotspot,site,part,random,geometry,makeWater"
    source = "\n\n".join(f"const part{i} = (ctx) => {{ const {{{bindings}}} = ctx; return (\n{codes[i]}\n)(ctx); }};" for i in range(8))
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--output", type=Path, default=ROOT / "runs" / time.strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--parallel", type=int, choices=(1, 8), default=8)
    parser.add_argument("--max-tokens", type=int, default=2800)
    parser.add_argument('--contract', choices=('full', 'compact'), default='full')
    parser.add_argument("--plan", type=Path)
    parser.add_argument('--live-status', action='store_true')
    parser.add_argument('--request-order', help='Permutation of component ids, comma separated')
    parser.add_argument('--repair-from',type=Path)
    parser.add_argument('--feedback',type=Path)
    args = parser.parse_args()
    request_order = None
    if args.request_order:
        try:
            request_order = [int(x) for x in args.request_order.split(',')]
        except ValueError:
            parser.error('request-order must contain integer component ids')
        if sorted(request_order) != list(range(8)):
            parser.error('request-order must contain ids 0 through 7 exactly once')
    if bool(args.repair_from)!=bool(args.feedback):
        parser.error('--repair-from and --feedback must be supplied together')
    args.output.mkdir(parents=True, exist_ok=False)
    if args.repair_from:
        source=args.repair_from.resolve()
        feedback=json.loads(args.feedback.read_text(encoding='utf-8'))
        if not feedback or any(str(i) not in [str(n) for n in range(8)] or not isinstance(v,str) or not v.strip() for i,v in feedback.items()):
            raise ValueError('Feedback must map component IDs 0..7 to observed problems')
        prompt=(source/'prompt.txt').read_text(encoding='utf-8')
        plan=json.loads((source/'plan.json').read_text());validate_plan(plan)
        codes={i:(source/f'part{i}.js').read_text(encoding='utf-8') for i in range(8)}
        (args.output/'prompt.txt').write_text(prompt,encoding='utf-8')
        (args.output/'plan.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
        (args.output/'feedback.json').write_text(json.dumps(feedback,indent=2),encoding='utf-8')
        start=time.perf_counter();receipts={};failures=[]
        with ThreadPoolExecutor(max_workers=min(args.parallel,len(feedback))) as pool:
            futures={pool.submit(generate_part,plan,plan['parts'][int(i)],prompt,args.output,args.max_tokens,review,args.contract):i for i,review in feedback.items()}
            for future in as_completed(futures):
                try:
                    i,code,receipt=future.result();codes[i]=code;receipts[i]=receipt
                except Exception as error:
                    failures.append({'part':futures[future],'error':str(error)})
        if not failures:
            for i,code in codes.items():(args.output/f'part{i}.js').write_text(code,encoding='utf-8')
            assemble(plan,codes,args.output)
        summary={'type':'targeted_visual_refinement','source':str(source),'changed_parts':list(receipts),'failures':failures,'refinement_seconds':time.perf_counter()-start,'includes_browser_validation':False,'parts':receipts}
        (args.output/'summary.json').write_text(json.dumps(summary,indent=2))
        print(json.dumps({k:v for k,v in summary.items() if k!='parts'},indent=2))
        if failures:raise SystemExit(1)
        return
    (args.output / "prompt.txt").write_text(args.prompt, encoding="utf-8")
    started = time.perf_counter()
    if args.plan:
        plan, plan_receipt = json.loads(args.plan.read_text(encoding="utf-8")), None
        (args.output / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    else:
        plan, plan_receipt = make_plan(args.prompt, args.output)
    generation_start = time.perf_counter()
    if args.live_status:
        (args.output / 'live-start.json').write_text(json.dumps({'started_perf': generation_start}))
    codes, receipts, failures = {}, {}, []
    ordered_parts = [next(p for p in plan['parts'] if p['id'] == i) for i in request_order] if request_order else plan['parts']
    admissions = [Event() for _ in range(9)] if request_order else None
    if admissions:
        admissions[0].set()
    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = {pool.submit(generate_part, plan, part, args.prompt, args.output, args.max_tokens,
                    contract=args.contract, admission=(admissions[j], admissions[j + 1]) if admissions else None): part["id"]
                   for j, part in enumerate(ordered_parts)}
        for future in as_completed(futures):
            try:
                number, code, receipt = future.result()
                codes[number], receipts[number] = code, receipt
            except Exception as error:
                failures.append({"part": futures[future], "error": str(error)})
    generated_at = time.perf_counter()
    if not failures:
        assemble(plan, codes, args.output)
    counts = [r["usage"].get("completion_tokens") for r in receipts.values()]
    total = sum(counts) if counts and all(isinstance(n, int) for n in counts) else None
    generation_seconds = generated_at - generation_start
    elapsed = time.perf_counter() - started
    known_spent=sum(r["usage"].get("completion_tokens", 0) + r.get("initial_attempt", {}).get("usage", {}).get("completion_tokens", 0) for r in receipts.values())
    accounting_complete=not failures and not any(r.get('initial_attempt',{}).get('completion_tokens_unknown') for r in receipts.values())
    summary = {"prompt": args.prompt, "parallel": args.parallel, "contract": args.contract, "request_order": request_order, "sections_valid": len(codes),
               "failures": failures, "planning_seconds": generation_start-started,
               "generation_seconds": generation_seconds, "artifact_seconds": elapsed,
               "generated_completion_tokens": total,
               "spent_completion_tokens": known_spent if accounting_complete else None,
               "known_spent_completion_tokens":known_spent,"token_accounting_complete":accounting_complete,
               "repaired_sections": [i for i, r in receipts.items() if "initial_attempt" in r],
               "generation_aggregate_tps": total/generation_seconds if total else None,
               "artifact_useful_tps": total/elapsed if total else None,
               "includes_browser_validation": False, "includes_runtime_loading": False,
               "used_existing_plan": bool(args.plan), "planner": plan_receipt, "parts": receipts}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k not in ("planner", "parts")}, indent=2), flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
