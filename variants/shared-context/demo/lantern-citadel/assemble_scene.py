"""Validate eight new components and assemble them with the existing tested scene host."""
import json
from pathlib import Path
import re
import sys

WORK = Path(__file__).resolve().parent
BASE = next((parent / 'variants/fanout' for parent in WORK.parents
             if (parent / 'variants/fanout/fanout.py').is_file()), None)
if BASE is None:
    raise RuntimeError('Keep this demo workspace inside the qwen-parallel-lab-tensorfold repository.')
sys.path.insert(0, str(BASE))
import fanout

plan = json.loads((WORK / 'plan.json').read_text(encoding='utf-8'))
fanout.validate_plan(plan)
codes = {}
for index in range(8):
    path = WORK / f'part{index}.js'
    code = path.read_text(encoding='utf-8').strip()
    if not re.match(rf'^function\s+part{index}\s*\(\s*ctx\s*\)', code):
        raise ValueError(f'{path.name}: expected plain function part{index}(ctx)')
    fanout.syntax_check(code, path, index)
    codes[index] = code
    print(f'PASS {path.name}: syntax, identifiers and component contract')
output = WORK / 'site'
output.mkdir(exist_ok=True)
fanout.assemble(plan, codes, output)
receipt = {'components': 8, 'passed': True, 'output': str(output / 'index.html'),
           'scope': 'Static integration only; rendered scene and interactions require browser checks.'}
(WORK / 'assembly-receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
print(json.dumps(receipt))
