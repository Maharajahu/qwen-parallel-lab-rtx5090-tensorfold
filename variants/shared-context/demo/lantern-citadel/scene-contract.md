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
geometry.arch(width,height,depth,thickness,material) returns a ready THREE.Object3D pointed OPEN arch,
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

Keep each proposal at most 1300 tokens. Return one fully closed function in a JavaScript code block, without long explanations. The coordinator will place it in partN.js and run assemble_scene.py.

IMPORTANT: geometry.gable(), geometry.arch() and geometry.window() return ready Object3D objects, NOT BufferGeometry. Add these objects directly to the scene/group. For repeated copies use object.clone(true). Never pass their return values to new THREE.Mesh().
