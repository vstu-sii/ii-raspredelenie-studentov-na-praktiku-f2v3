"""Langfuse SDK tracing and an explicit local development sink."""
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path


class Attempt:
    def __init__(self, generation, record, capture):
        self.generation, self.record, self.capture = generation, record, capture

    def status(self, code):
        self.record["http_status"] = code

    def output(self, text):
        if self.capture:
            self.record["output"] = text
            if self.generation:
                self.generation.update(output=text)

    def usage(self, usage):
        clean = {key: value for key, value in usage.items()
                 if key in {"prompt_tokens", "completion_tokens"} and isinstance(value, int)}
        self.record.update(clean)
        if self.generation:
            self.generation.update(usage_details={
                {"prompt_tokens": "input", "completion_tokens": "output"}[k]: v
                for k, v in clean.items()})

    def error(self, reason):
        self.record["error"] = reason
        if self.generation:
            self.generation.update(level="ERROR", status_message=reason)


class Tracer:
    def __init__(self, mode=None, path=None, capture=None):
        self.mode = mode or os.getenv("AI_TRACING_MODE", "langfuse")
        self.path = Path(path or os.getenv("AI_TRACE_PATH", "var/llm-calls.jsonl"))
        self.capture = capture if capture is not None else os.getenv("AI_TRACE_CONTENT", "false").lower() == "true"
        self.client = None
        if self.mode == "langfuse":
            if not os.getenv("LANGFUSE_PUBLIC_KEY") or not os.getenv("LANGFUSE_SECRET_KEY"):
                raise RuntimeError("Set Langfuse keys or explicitly select AI_TRACING_MODE=local for development")
            from langfuse import get_client
            self.client = get_client()
        elif self.mode != "local":
            raise ValueError("AI_TRACING_MODE must be langfuse or local")

    @contextmanager
    def attempt(self, request_id, model, messages, attempt, prompt_version):
        record = {"request_id": request_id, "model": model, "attempt": attempt,
                  "prompt_version": prompt_version}
        if self.capture:
            record["input"] = messages
        started = time.perf_counter()
        try:
            if self.client:
                with self.client.start_as_current_observation(
                    name="vkr.baseline.attempt", as_type="generation", model=model,
                    input=messages if self.capture else None,
                    metadata=record.copy(), version=prompt_version,
                ) as generation:
                    yield Attempt(generation, record, self.capture)
            else:
                yield Attempt(None, record, self.capture)
        finally:
            record["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as target:
                target.write(json.dumps(record, ensure_ascii=False) + "\n")

    def flush(self):
        if self.client:
            self.client.flush()
