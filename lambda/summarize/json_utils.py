"""Defensive JSON extraction for models without guaranteed structured output.

Amazon Nova (and most non-Anthropic Bedrock models) don't have an
API-enforced JSON schema the way Claude's `output_config.format` does —
they're prompted to return JSON and usually comply, but sometimes wrap it in
a markdown code fence or add a stray sentence before/after. This strips the
common wrapping patterns before parsing, and raises a clear error (rather
than a raw JSONDecodeError) when the model genuinely didn't return JSON, so
the Step Functions Retry on the calling state has something meaningful to
retry against.
"""
import json
import re

_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def parse_json_response(text: str) -> dict:
    text = text.strip()

    fenced = _CODE_FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1).strip()

    # Fallback: if there's still leading/trailing prose, take the first
    # {...} block — models occasionally prefix JSON with a sentence despite
    # instructions not to.
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            text = text[start : end + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model response was not valid JSON: {text[:300]!r}") from exc
