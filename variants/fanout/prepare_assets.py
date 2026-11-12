"""Fetch an integrity-verified Three.js package from the official npm registry."""
import base64
import hashlib
import io
import json
from pathlib import Path
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parent
meta = json.load(urllib.request.urlopen("https://registry.npmjs.org/three/0.180.0", timeout=30))
blob = urllib.request.urlopen(meta["dist"]["tarball"], timeout=60).read()
algorithm, expected = meta["dist"]["integrity"].split("-", 1)
assert algorithm == "sha512"
assert base64.b64encode(hashlib.sha512(blob).digest()).decode() == expected
vendor = ROOT / "vendor"
vendor.mkdir(exist_ok=True)
files = []
with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
    for name in ("build/three.module.min.js", "build/three.core.min.js", "examples/jsm/objects/Reflector.js", "LICENSE"):
        member = archive.getmember("package/" + name)
        assert member.isfile()
        data = archive.extractfile(member).read()
        destination = vendor / Path(name).name
        destination.write_bytes(data)
        files.append({"name": destination.name, "sha256": hashlib.sha256(data).hexdigest()})
(vendor / "manifest.json").write_text(json.dumps({"package": "three", "version": "0.180.0", "npm_integrity": meta["dist"]["integrity"], "files": files}, indent=2))
print(json.dumps({"verified": True, "files": files}))
