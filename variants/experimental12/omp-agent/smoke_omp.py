"""Load the installed OMP extension over RPC without sending a model prompt."""
import json
import os
from pathlib import Path
import subprocess

APP = Path(__file__).resolve().parent
LAB = APP.parent
OMP = LAB.parent.parent / '.runtime/omp/omp.exe'
env = os.environ.copy()
env['PI_CODING_AGENT_DIR'] = str(APP / 'profile')
command = [str(OMP), '--cwd', str(APP), '--mode', 'rpc', '--no-ui', '--no-session',
           '--model', 'TensorFold-Shared/qwen27-sync-speed', '--system-prompt', str(APP / 'system.txt'),
           '--tools', 'workspace_file,workspace_terminal,parallel_tasks', '--extension', str(APP / 'shared-extension.ts'),
           '--no-lsp', '--no-skills', '--no-rules', '--no-context-files', '--no-extensions', '--no-title', '--thinking', 'low']
process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           env=env, cwd=APP, creationflags=subprocess.CREATE_NO_WINDOW)
try:
    out, err = process.communicate(b'{"id":"offline-startup","type":"get_state"}\n', timeout=20)
except subprocess.TimeoutExpired:
    process.kill()
    out, err = process.communicate()
    raise RuntimeError(f'OMP RPC did not exit after stdin closed: {err.decode(errors="replace")}')
stdout, stderr = out.decode('utf-8', errors='replace'), err.decode('utf-8', errors='replace')
rows = []
for line in stdout.splitlines():
    try:
        rows.append(json.loads(line))
    except json.JSONDecodeError:
        pass
reply = next((row for row in rows if row.get('id') == 'offline-startup'), None)
receipt = {'exit_code': process.returncode, 'request': 'get_state only; no inference',
           'reply': reply, 'stdout': stdout, 'stderr': stderr}
(APP / 'omp-startup-receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
if process.returncode or not reply or not reply.get('success'):
    raise RuntimeError(json.dumps(receipt, indent=2))
if 'extension' in stderr.lower() and ('error' in stderr.lower() or 'fail' in stderr.lower()):
    raise RuntimeError(stderr)
print(json.dumps({'exit_code': process.returncode, 'rpc_success': reply.get('success'),
                  'receipt': str(APP / 'omp-startup-receipt.json'), 'stderr': stderr}, indent=2))
