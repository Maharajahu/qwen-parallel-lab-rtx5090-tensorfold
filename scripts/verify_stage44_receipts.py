"""Verify archived Stage44 output IDs and recompute medians; no GPU or network."""
import hashlib
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1] / 'results/blackfury-stage44'

def verify():
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    assert len(manifest['requests']) == 32
    reference = None
    rates = {}
    for row in manifest['requests']:
        folder = ROOT / 'requests' / row['case']
        for name, key in [('receipt.json', 'sha256'), ('response.sse', 'sse_sha256')]:
            assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == row[key], row['case']
        receipt = json.loads((folder / 'receipt.json').read_text())
        chunks = [json.loads(line[6:]) for line in (folder / 'response.sse').read_text().splitlines()
                  if line.startswith('data: ') and line[6:] != '[DONE]']
        native = next(c['tensorfold'] for c in reversed(chunks) if 'tensorfold' in c)
        usage = next(c['usage'] for c in reversed(chunks) if 'usage' in c)
        assert usage == receipt['usage']
        assert native['token_ids'] == receipt['native']['token_ids']
        ids = native['token_ids']
        assert len(ids) == 2048 and usage['prompt_tokens'] == 129024
        if reference is None:
            reference = ids
        assert ids == reference, row['case']
        cell, phase = row['case'].split('/')
        mode, arm = cell.split('-')
        if phase != 'cold':
            rates.setdefault((mode, arm[0]), []).append(native['tokens_per_second'])
    result = {f'{mode}-{arm}': statistics.median(values) for (mode, arm), values in rates.items()}
    print(json.dumps({'verified_requests': 32, 'all_2048_output_ids_identical': True,
                      'warm_decode_medians_tps': result}, indent=2))
    return result

if __name__ == '__main__':
    verify()
