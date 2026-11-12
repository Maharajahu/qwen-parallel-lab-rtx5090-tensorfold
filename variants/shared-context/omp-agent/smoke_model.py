"""Opt-in real-model E2E qualification. Never starts/stops the existing runtime."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import uuid


APP = Path(__file__).resolve().parent
LAB = APP.parent
OMP = LAB.parent.parent / '.runtime/omp/omp.exe'
BASE_URL = 'http://127.0.0.1:18192'
MODEL = 'qwen27-shared-agent'
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
CONTRACT = '''Implement size_parser.py with parse_size(value: str) -> int and test_size_parser.py using only Python's standard library.
The input is a nonnegative integer followed by exactly B, KiB or MiB (case-sensitive). Surrounding whitespace and whitespace between the integer and unit are allowed. Return bytes as an int; multipliers are 1, 1024 and 1048576. Examples: "0B" -> 0, " 2 KiB " -> 2048, "3MiB" -> 3145728.
Empty input, missing unit, negative/fractional numbers and unknown units must raise ValueError. Test at least these invalid strings: "", "1", "-1 B", "1.5KiB", "4 KB". Test at least five separate unittest methods. No external packages, network, background processes or changes outside this workspace.'''
PROMPT = f'''Complete this small real coding task in this workspace:
{CONTRACT}

First call parallel_tasks EXACTLY ONCE with EXACTLY TWO read-only tasks, IDs "implementation" and "tests". The implementation task owns only size_parser.py; the tests task owns only test_size_parser.py. Give both the shared contract above, max_tokens 4096, and an empty shared_files list. They must propose compatible changes, not write files.
When both proposals return, YOU integrate them into the actual files with workspace_file. Run workspace_terminal with exactly the command "python -m unittest -v" and fix any real failures. Finish with one concise conclusion based on actual results. Do not merely describe code or claim that a proposal is already implemented. Do not ask for routine confirmation.'''
SEMANTIC_PROBE = '''from size_parser import parse_size
for text, expected in [("0B", 0), (" 2 KiB ", 2048), ("3MiB", 3145728), ("17 B", 17), ("1KiB", 1024)]:
    actual = parse_size(text)
    assert type(actual) is int and actual == expected, (text, actual, expected)
for text in ["", "1", "-1 B", "1.5KiB", "4 KB", "2 kib"]:
    try:
        parse_size(text)
    except ValueError:
        pass
    else:
        raise AssertionError((text, "ValueError required"))
print("Independent semantic checks passed")
'''


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def http_json(path):
    with OPENER.open(BASE_URL + path, timeout=10) as response:
        return json.load(response)


def snapshot(path):
    try:
        return http_json(path)
    except Exception as error:
        return {'unavailable': str(error)}


def read_events(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def stream_reader(stream, target, messages=None):
    with target.open('w', encoding='utf-8') as log:
        for raw in iter(stream.readline, b''):
            text = raw.decode('utf-8', errors='replace')
            log.write(text)
            log.flush()
            if messages is not None:
                try:
                    row = json.loads(text)
                except json.JSONDecodeError:
                    continue
                messages.put(row)
    if messages is not None:
        messages.put(None)


def send(process, message):
    process.stdin.write((json.dumps(message, ensure_ascii=False) + '\n').encode('utf-8'))
    process.stdin.flush()


def wait_rpc(messages, process, deadline, predicate, description, collected):
    while time.monotonic() < deadline:
        try:
            row = messages.get(timeout=min(1, max(.01, deadline - time.monotonic())))
        except queue.Empty:
            if process.poll() is not None:
                raise RuntimeError(f'OMP exited {process.returncode} while waiting for {description}')
            continue
        if row is None:
            raise RuntimeError(f'OMP closed stdout before {description}')
        collected.append(row)
        if predicate(row):
            return row
    raise TimeoutError(f'Timed out waiting for {description}')


def stop_own_omp(process, completed, messages, collected):
    """Abort only this OMP run; leave the externally owned native runtime alone."""
    if process is None:
        return {'exit_code': None, 'forced': False}
    forced = False
    if process.poll() is None and not completed:
        try:
            send(process, {'id': 'e2e-cleanup-abort', 'type': 'abort'})
            wait_rpc(messages, process, time.monotonic() + 8,
                     lambda row: row.get('type') == 'agent_end', 'abort agent_end', collected)
        except (OSError, RuntimeError, TimeoutError):
            pass
    if process.stdin and not process.stdin.closed:
        try:
            process.stdin.close()
        except OSError:
            pass
    if process.poll() is None:
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            forced = True
            if os.name == 'nt':
                subprocess.run(['taskkill.exe', '/pid', str(process.pid), '/t', '/f'], capture_output=True, timeout=5)
            else:
                process.kill()  # exact child handle, never a process-name or server kill
            process.wait(timeout=5)
    return {'exit_code': process.returncode, 'forced': forced}


def qualify(run, work, events, require_cache):
    calls = [e['event'] for e in events if e.get('type') == 'tool_call']
    results = [e['event'] for e in events if e.get('type') == 'tool_result']
    batch_calls = [e for e in calls if e.get('toolName') == 'parallel_tasks']
    if len(batch_calls) != 1:
        raise AssertionError(f'Expected one real parallel_tasks call, observed {len(batch_calls)}')
    arguments = batch_calls[0].get('input') or batch_calls[0].get('args') or {}
    if sorted(t.get('id') for t in arguments.get('tasks', [])) != ['implementation', 'tests']:
        raise AssertionError(f'Actual branch tasks differ from the requested pair: {arguments}')
    batch_results = [e for e in results if e.get('toolName') == 'parallel_tasks' and not e.get('isError')]
    if len(batch_results) != 1:
        raise AssertionError('A successful real parallel_tasks result was not observed')
    summary = batch_results[0].get('details', {}).get('summary')
    if not summary or summary.get('status') != 'complete' or len(summary.get('branches', [])) != 2:
        raise AssertionError('Missing completed native branch receipts in the real tool result')
    source = Path(summary['directory']).resolve()
    if not source.is_relative_to((APP / 'runs').resolve()):
        raise AssertionError(f'Unexpected branch receipt path: {source}')
    native_summary = read_json(source / 'summary.json')
    if native_summary.get('run_id') != summary.get('run_id') or native_summary.get('status') != 'complete':
        raise AssertionError('Persisted native summary does not match the real OMP result')
    prefix = read_json(source / 'common-prefix.tokens.json')
    digest = hashlib.sha256(json.dumps(prefix, separators=(',', ':')).encode()).hexdigest()
    if not prefix or len(prefix) != summary['rendered_common_prefix_tokens'] or digest != summary['rendered_common_prefix_sha256']:
        raise AssertionError('Recorded common token prefix hash/length failed verification')
    requests = [read_json(source / f'{name}.request.json') for name in ['implementation', 'tests']]
    if requests[0]['messages'][:-1] != requests[1]['messages'][:-1]:
        raise AssertionError('Actual recorded branch requests have different shared messages')
    branches = []
    for name in ['implementation', 'tests']:
        receipt = read_json(source / f'{name}.receipt.json')
        if not receipt.get('done') or receipt.get('finish_reason') != 'stop':
            raise AssertionError(f'{name} did not finish normally')
        if not isinstance(receipt.get('usage', {}).get('completion_tokens'), int):
            raise AssertionError(f'{name} has no measured completion token count')
        cached = receipt.get('usage', {}).get('prompt_tokens_details', {}).get('cached_tokens')
        if not isinstance(cached, int) or cached < 0:
            raise AssertionError(f'{name} has no measured native cached_tokens receipt')
        branches.append({'id': name, 'cached_tokens': cached, 'receipt': receipt,
                         'receipt_path': str(source / f'{name}.receipt.json')})
    cache_hit = any(b['cached_tokens'] > 0 for b in branches)
    if require_cache and not cache_hit:
        raise AssertionError('No positive cached_tokens observed; the requested cache gate failed')
    test_calls = [e for e in calls if e.get('toolName') == 'workspace_terminal' and
                  (e.get('input') or e.get('args') or {}).get('command', '').strip() == 'python -m unittest -v']
    if not test_calls:
        raise AssertionError('Coordinator did not call the required real unittest command')
    test_ids = {e.get('toolCallId') for e in test_calls}
    if not any(e.get('toolName') == 'workspace_terminal' and e.get('toolCallId') in test_ids and
               not e.get('isError') and e.get('details', {}).get('exit_code') == 0 for e in results):
        raise AssertionError('Coordinator has no matching successful test tool receipt')
    files = {}
    for name in ['size_parser.py', 'test_size_parser.py']:
        path = work / name
        if not path.is_file() or path.is_symlink() or not path.stat().st_size:
            raise AssertionError(f'Missing real output file: {path}')
        files[name] = {'path': str(path), 'bytes': path.stat().st_size,
                       'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    command = [sys.executable, '-m', 'unittest', '-v']
    tests = subprocess.run(command, cwd=work, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
    (run / 'independent-unittest.stdout.txt').write_text(tests.stdout, encoding='utf-8')
    (run / 'independent-unittest.stderr.txt').write_text(tests.stderr, encoding='utf-8')
    count = re.search(r'Ran (\d+) tests?', tests.stdout + tests.stderr)
    if tests.returncode or not count or int(count[1]) < 5 or 'skipped=' in tests.stdout + tests.stderr:
        raise AssertionError(f'Independent unittest verification failed: exit {tests.returncode}; {tests.stderr[-3000:]}')
    probe = subprocess.run([sys.executable, '-c', SEMANTIC_PROBE], cwd=work, capture_output=True,
                           text=True, encoding='utf-8', errors='replace', timeout=30)
    (run / 'independent-semantics.stdout.txt').write_text(probe.stdout, encoding='utf-8')
    (run / 'independent-semantics.stderr.txt').write_text(probe.stderr, encoding='utf-8')
    if probe.returncode:
        raise AssertionError(f'Independent contract checks failed: {probe.stderr[-3000:]}')
    return {'real_tool_calls': [e.get('toolName') for e in calls], 'branch_run': str(source),
            'rendered_common_prefix_tokens': len(prefix), 'rendered_common_prefix_sha256': digest,
            'branches': branches, 'cache_reuse_observed': cache_hit, 'files': files,
            'coordinator_test_exit_code': 0, 'independent_test_exit_code': tests.returncode,
            'independent_test_count': int(count[1]), 'independent_semantics_exit_code': probe.returncode}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-directory', type=Path, help='New directory only; default omp-agent/model-smoke/<unique-id>')
    parser.add_argument('--timeout', type=int, default=300, help='Overall OMP deadline in seconds')
    parser.add_argument('--require-cache-hit', action='store_true', help='Also require a measured positive native cached_tokens value')
    parser.add_argument('--continuation', action='store_true', help='Verify a second user turn modifies the same project and conversation')
    args = parser.parse_args()
    if not 30 <= args.timeout <= 1800:
        parser.error('--timeout must be between 30 and 1800 seconds')
    run = (args.run_directory or APP / 'model-smoke' / f'{time.strftime("%Y%m%d-%H%M%S")}-{uuid.uuid4().hex[:8]}').resolve()
    run.mkdir(parents=True, exist_ok=False)
    work = run / 'work'
    work.mkdir()
    started = time.monotonic()
    receipt = {'status': 'running', 'run_directory': str(run), 'work_directory': str(work), 'prompt': PROMPT,
               'runtime_policy': 'Existing runtime only; no runtime start/stop', 'require_cache_hit': args.require_cache_hit}
    process = None
    readers = []
    messages = queue.Queue()
    collected = []
    completed = False
    try:
        health = http_json('/health')
        receipt['health_before'] = health
        if health.get('status') != 'ok' or health.get('model') != MODEL:
            raise RuntimeError(f'Expected healthy existing {MODEL} on {BASE_URL}; observed {health}')
        receipt['load_before'] = snapshot('/v1/load')
        env = os.environ.copy()
        env['PATH'] = str(Path(sys.executable).parent) + os.pathsep + env.get('PATH', '')
        env['PI_CODING_AGENT_DIR'] = str(APP / 'profile')
        env['SHARED_AGENT_EVENTS'] = str(run / 'agent-events.jsonl')
        command = [str(OMP), '--cwd', str(work), '--mode', 'rpc', '--no-ui', '--no-session', '--auto-approve',
                   '--model', f'TensorFold-Shared/{MODEL}', '--system-prompt', str(APP / 'system.txt'),
                   '--tools', 'workspace_file,workspace_terminal,parallel_tasks', '--extension', str(APP / 'shared-extension.ts'),
                   '--no-lsp', '--no-skills', '--no-rules', '--no-context-files', '--no-extensions', '--no-title', '--thinking', 'low']
        receipt['omp_command'] = command
        process = subprocess.Popen(command, cwd=work, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        receipt['owned_omp_pid'] = process.pid
        for stream, path, output_queue in [(process.stdout, run / 'rpc.stdout.jsonl', messages), (process.stderr, run / 'rpc.stderr.txt', None)]:
            thread = threading.Thread(target=stream_reader, args=(stream, path, output_queue), daemon=True)
            thread.start()
            readers.append(thread)
        deadline = started + args.timeout
        send(process, {'id': 'e2e-state', 'type': 'get_state'})
        state = wait_rpc(messages, process, min(deadline, time.monotonic() + 25),
                         lambda row: row.get('id') == 'e2e-state', 'startup get_state', collected)
        receipt['startup_state'] = state
        if not state.get('success') or state.get('data', {}).get('model', {}).get('id') != MODEL:
            raise RuntimeError(f'Unexpected OMP startup state: {state}')
        send(process, {'id': 'e2e-prompt', 'type': 'prompt', 'message': PROMPT})
        ended = wait_rpc(messages, process, deadline,
                         lambda row: row.get('type') == 'agent_end' and not row.get('willContinue'), 'real agent_end', collected)
        receipt['agent_end'] = ended
        completed = True
        # This RPC barrier lets extension agent_end hooks finish before their log is inspected.
        send(process, {'id': 'e2e-idle', 'type': 'get_state'})
        idle = wait_rpc(messages, process, min(deadline, time.monotonic() + 10),
                        lambda row: row.get('id') == 'e2e-idle', 'post-agent_end get_state', collected)
        receipt['idle_state'] = idle
        if not idle.get('success') or idle.get('data', {}).get('isStreaming') is True:
            raise AssertionError('OMP did not become idle after agent_end')
        events = read_events(run / 'agent-events.jsonl')
        receipt['verification'] = qualify(run, work, events, args.require_cache_hit)
        final_turns = [e for e in events if e.get('type') == 'agent_end' and not e['event'].get('willContinue')]
        if len(final_turns) != 1:
            raise AssertionError(f'Expected one completed OMP turn, observed {len(final_turns)}')
        assistants = [m for m in final_turns[0]['event'].get('messages', []) if m.get('role') == 'assistant']
        if not assistants or assistants[-1].get('stopReason') != 'stop':
            raise AssertionError('Coordinator did not finish with a normal final assistant response')
        conclusion = ''.join(item.get('text', '') for item in assistants[-1].get('content', []) if item.get('type') == 'text')
        if not conclusion.strip():
            raise AssertionError('Coordinator returned no final conclusion')
        receipt['conclusion'] = conclusion
        if args.continuation:
            completed = False
            followup = ('Extend the parser from the previous turn to accept GiB with multiplier 1073741824. '
                        'Preserve all existing behavior and tests; add a new test method for 2GiB. '
                        'Apply the actual changes and run the tests. Do not use branches for this small change.')
            send(process, {'id': 'continuation', 'type': 'prompt', 'message': followup})
            wait_rpc(messages, process, deadline,
                     lambda row: row.get('type') == 'agent_end' and not row.get('willContinue'), 'continuation', collected)
            completed = True
            send(process, {'id': 'continuation-idle', 'type': 'get_state'})
            wait_rpc(messages, process, min(deadline, time.monotonic() + 10),
                     lambda row: row.get('id') == 'continuation-idle', 'continuation idle', collected)
            check = subprocess.run([sys.executable, '-c', SEMANTIC_PROBE + '\nassert parse_size("2GiB") == 2147483648\n'],
                                   cwd=work, text=True, encoding='utf-8', capture_output=True, timeout=30)
            tests = subprocess.run([sys.executable, '-m', 'unittest', '-v'], cwd=work, text=True,
                                   encoding='utf-8', capture_output=True, timeout=30)
            (run / 'continuation-checks.txt').write_text(check.stdout + check.stderr + tests.stdout + tests.stderr, encoding='utf-8')
            continued = read_events(run / 'agent-events.jsonl')[len(events):]
            final_count = sum(e['type'] == 'agent_end' and not e['event'].get('willContinue') for e in continued)
            real_test = any(e['type'] == 'tool_result' and e['event'].get('toolName') == 'workspace_terminal'
                            and not e['event'].get('isError') and e['event'].get('details', {}).get('exit_code') == 0 for e in continued)
            new_tests = re.search(r'Ran (\d+) tests?', tests.stderr + tests.stdout)
            if (check.returncode or tests.returncode or final_count != 1 or not real_test
                    or not new_tests or int(new_tests[1]) <= receipt['verification']['independent_test_count']):
                raise AssertionError('Same-conversation follow-up did not preserve, extend and test the real project')
            receipt['continuation'] = {'passed': True, 'same_omp_pid': process.pid, 'prompt': followup,
                                       'independent_test_count': int(new_tests[1]), 'semantics_exit_code': check.returncode,
                                       'tests_exit_code': tests.returncode}
        receipt['status'] = 'passed'
    except Exception as error:
        receipt['status'] = 'failed'
        receipt['error'] = str(error)
        receipt['traceback'] = traceback.format_exc()
    finally:
        try:
            receipt['omp_cleanup'] = stop_own_omp(process, completed, messages, collected)
            if receipt['status'] == 'passed' and (receipt['omp_cleanup']['forced'] or receipt['omp_cleanup']['exit_code'] != 0):
                receipt['status'] = 'failed'
                receipt['error'] = f"OMP cleanup did not exit normally: {receipt['omp_cleanup']}"
        except Exception as error:
            receipt['status'] = 'failed'
            receipt['cleanup_error'] = str(error)
        for thread in readers:
            thread.join(timeout=2)
        receipt['health_after'] = snapshot('/health')
        receipt['load_after'] = snapshot('/v1/load')
        receipt['elapsed_seconds'] = time.monotonic() - started
        (run / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status': receipt['status'], 'receipt': str(run / 'receipt.json'), 'error': receipt.get('error')}, ensure_ascii=False, indent=2))
    return 0 if receipt['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
