"""Measured streaming requests. Preserve raw receipts, never estimate token counts."""
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

from runtime_control import URL


def complete(messages, target: Path, max_tokens=2048, temperature=0, extra=None, admission=None):
    try:
        return _complete(messages, target, max_tokens, temperature, extra, admission)
    finally:
        # Failed preparation must also release the next request in the batch.
        if admission:
            admission[1].set()


def _complete(messages, target, max_tokens, temperature, extra, admission):
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"model": "qwen27-fanout", "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens,
               "stream": True, "stream_options": {"include_usage": True}}
    if extra:
        payload.update(extra)
    start = time.perf_counter()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    token_request = urllib.request.Request(URL + "/tokenize", data=json.dumps({"messages": messages, "add_generation_prompt": True}).encode(),
                                          headers={"Content-Type": "application/json"})
    with opener.open(token_request, timeout=30) as response:
        token_info = json.load(response)
    # DFlash2 verifies speculative blocks of up to 64 rows. A nearly full context
    # can fail before the requested output cap; keep two blocks of device space.
    headroom = 128
    available = token_info["max_model_len"] - token_info["count"] - headroom
    if available < 256:
        raise ValueError(f"Prompt leaves only {available} tokens for output")
    payload["max_tokens"] = min(max_tokens, available)
    target.with_suffix(".request.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    request = urllib.request.Request(URL + "/v1/chat/completions", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
    first = last = None
    chunks, reasoning, usage, finish, done = [], [], {}, None, False
    runtime_stats = {}
    try:
        if admission and not admission[0].wait(timeout=60):
            raise RuntimeError('Timed out waiting for ordered request admission')
        with opener.open(request, timeout=600) as response, target.with_suffix(".events.jsonl").open("w", encoding="utf-8") as events:
            # HTTP headers acknowledge admission; generation stays concurrent.
            if admission:
                admission[1].set()
            for raw in response:
                line = raw.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                now = time.perf_counter()
                if data == "[DONE]":
                    done = True
                    break
                event = json.loads(data)
                events.write(json.dumps({"elapsed": now - start, "received_at_ms": time.time_ns() // 1_000_000, "event": event}, ensure_ascii=False) + "\n")
                events.flush()
                if event.get("error"):
                    target.with_suffix('.failure.json').write_text(json.dumps({
                        'error':event['error'],'elapsed_seconds':now-start,
                        'partial_content_chars':sum(map(len,chunks)),
                        'usage':usage,'completion_tokens_unknown':not bool(usage),
                        'preflight_prompt_tokens':token_info['count'],
                        'context_headroom':headroom},indent=2))
                    raise RuntimeError(str(event["error"]))
                if event.get("usage"):
                    usage = event["usage"]
                if event.get("tensorfold"):
                    runtime_stats.update(event["tensorfold"])
                for choice in event.get("choices", []):
                    delta = choice.get("delta", {})
                    if delta.get("content"):
                        chunks.append(delta["content"])
                        first = first or now
                        last = now
                    if delta.get("reasoning_content"):
                        reasoning.append(delta["reasoning_content"])
                    finish = choice.get("finish_reason") or finish
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        target.with_suffix(".error.txt").write_text(body, encoding="utf-8")
        raise RuntimeError(f"HTTP {error.code}: {body[:1500]}") from error
    elapsed = time.perf_counter() - start
    content = "".join(chunks)
    target.with_suffix(".txt").write_text(content, encoding="utf-8")
    receipt = {"elapsed_seconds": elapsed, "ttft_seconds": first - start if first else None,
               "visible_decode_seconds": last - first if first and last else None,
               "usage": usage, "runtime": runtime_stats, "finish_reason": finish, "done": done,
               "requested_max_tokens": max_tokens, "actual_max_tokens": payload["max_tokens"],
               "preflight_prompt_tokens": token_info["count"], "context_window": token_info["max_model_len"],
               "context_headroom": headroom,
               "content_chars": len(content), "reasoning_chars": sum(map(len, reasoning)),
               "started_perf": start, "first_perf": first, "last_perf": last,
               "finished_perf": start + elapsed}
    count = usage.get("completion_tokens")
    if count is not None:
        receipt["end_to_end_tps"] = count / elapsed
        if first and last and last > first:
            receipt["visible_window_tps"] = count / (last - first)
    target.with_suffix(".receipt.json").write_text(json.dumps(receipt, indent=2))
    if not done or not content:
        raise RuntimeError("Stream did not return a complete nonempty answer")
    return content, receipt


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt")
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "smoke/reply")
    parser.add_argument("--max-tokens", type=int, default=128)
    args = parser.parse_args()
    text, receipt = complete([{"role": "user", "content": args.prompt}], args.output, args.max_tokens)
    print(json.dumps({"text": text[:800], "receipt": receipt}, ensure_ascii=True, indent=2))
