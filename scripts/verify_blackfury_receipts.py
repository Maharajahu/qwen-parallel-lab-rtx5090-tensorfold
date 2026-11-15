"""Verify archived 131K receipts offline, or compare new SSE captures to the reference."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'results/blackfury-exact/reproduction'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def decode_sse(path):
    result = {'content': '', 'reasoning': '', 'native': {}, 'usage': {}, 'done': False}
    data = []
    for line in [*path.read_text(encoding='utf-8').splitlines(), '']:
        if line.startswith('data:'):
            data.append(line[5:].lstrip(' '))
        elif not line and data:
            payload = '\n'.join(data)
            data.clear()
            if payload == '[DONE]':
                result['done'] = True
                break
            event = json.loads(payload)
            require(not event.get('error'), f'{path}: server error {event.get("error")}')
            result['native'].update(event.get('tensorfold') or {})
            result['usage'] = event.get('usage') or result['usage']
            for choice in event.get('choices', []):
                delta = choice.get('delta', {})
                result['content'] += delta.get('content') or choice.get('text') or ''
                result['reasoning'] += delta.get('reasoning_content') or ''
                if choice.get('finish_reason'):
                    result['finish_reason'] = choice['finish_reason']
    return result


def check_output(row, reference, label):
    require(row['done'] and not row.get('error'), f'{label}: incomplete/failed stream')
    usage, native = row['usage'], row['native']
    require(usage['prompt_tokens'] == 129024 and usage['completion_tokens'] == 2048,
            f'{label}: expected 129024 input + 2048 output tokens')
    ids = native['token_ids']
    require(len(ids) == 2048, f'{label}: incomplete token IDs')
    require(digest(','.join(map(str, ids)).encode('ascii')) == native['token_sha256'],
            f'{label}: token hash differs from native receipt')
    require(ids == reference['native']['token_ids'], f'{label}: token IDs differ')
    for key in ('content', 'reasoning'):
        require(row[key].encode('utf-8') == reference[key].encode('utf-8'),
                f'{label}: {key} UTF-8 bytes differ')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--response', type=Path, action='append', default=[],
                        help='New response.sse to compare; repeat for multiple captures')
    args = parser.parse_args()
    manifest = read_json(ROOT / 'manifest.json')
    for item in manifest['files']:
        path = (ROOT / item['path']).resolve()
        require(path.is_relative_to(ROOT.resolve()), 'Manifest path escapes evidence directory')
        data = path.read_bytes()
        require(len(data) == item['bytes'] and digest(data) == item['sha256'],
                f'{item["path"]}: archive file hash/size differs')
    request = ROOT / 'request.json'
    require(digest(request.read_bytes()) == manifest['request_sha256'], 'Request hash differs')
    preflight = read_json(ROOT / 'preflight.json')
    require(preflight['count'] == len(preflight['tokens']) == 129024, 'Preflight count differs')
    reference = read_json(ROOT / manifest['reference_run'] / 'receipt.json')
    for item in manifest['rows']:
        label = item['run']
        receipt = read_json(ROOT / label / 'receipt.json')
        raw = decode_sse(ROOT / label / 'response.sse')
        identity = read_json(ROOT / label.split('/')[0] / 'identity.json')
        require(identity['binary_sha256'] == item['binary_sha256'], f'{label}: binary identity differs')
        require(digest(','.join(map(str, preflight['tokens'])).encode('ascii')) == identity['prompt_sha256'],
                f'{label}: preflight token hash differs')
        check_output(receipt, reference, label)
        check_output(raw, reference, label + '/response.sse')
        require(receipt['request_sha256'] == manifest['request_sha256'], f'{label}: wrong request')
        for key in ('content', 'reasoning', 'native', 'usage', 'done', 'finish_reason'):
            require(raw[key] == receipt[key], f'{label}: SSE and receipt differ for {key}')
        expected_cache = 0 if label.endswith('/cold') else 128896
        require(raw['usage']['prompt_tokens_details']['cached_tokens'] == expected_cache,
                f'{label}: unexpected prefix reuse')
        require(raw['native']['token_sha256'] == item['token_ids_sha256'], f'{label}: manifest token hash')
        for key in ('content', 'reasoning'):
            require(digest(raw[key].encode('utf-8')) == item[f'{key}_utf8_sha256'],
                    f'{label}: manifest {key} hash')
    for path in args.response:
        check_output(decode_sse(path), reference, str(path))
    print(json.dumps({'status': 'passed', 'archive_files_verified': len(manifest['files']),
                      'archived_requests_verified': len(manifest['rows']),
                      'new_responses_verified': len(args.response),
                      'token_ids_content_and_reasoning_equal': True}, indent=2))


if __name__ == '__main__':
    main()
