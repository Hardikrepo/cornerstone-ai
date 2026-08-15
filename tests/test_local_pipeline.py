"""Runs the classify + summarize Lambda logic locally with a mocked Bedrock
client, so the pipeline's data flow and JSON-parsing can be verified without
any AWS credentials or spend. The extract (Textract) step is skipped here
since it requires a live AWS call against an S3 object — this harness feeds
in text equivalent to what Textract would have extracted.

Run:
    pip install boto3
    python tests/test_local_pipeline.py
"""
import importlib.util
import json
import os
import sys
import uuid
from unittest.mock import patch

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "sample_docs"))
# Both classify/ and summarize/ ship an identical json_utils.py (each Lambda
# is packaged independently, so it's duplicated rather than shared via a
# layer) — either one on the path satisfies `from json_utils import ...`
# in both handler modules.
sys.path.insert(0, os.path.join(ROOT, "lambda", "classify"))

from generate_samples import INVOICE_LINES  # noqa: E402

SAMPLE_TEXT = "\n".join(INVOICE_LINES)


def _load_module(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_converse_response(payload: dict):
    """Shapes a fake Bedrock Converse API response carrying `payload` as the
    model's JSON text — matches what bedrock_runtime.converse() returns."""
    return {"output": {"message": {"content": [{"text": json.dumps(payload)}]}}}


def test_classify_and_summarize():
    fake_classification = {
        "document_type": "invoice",
        "confidence": "high",
        "reasoning": "Contains an invoice number, line items, and a total due.",
    }
    fake_summary = {
        "summary": "Invoice from Granite Peak Construction Supply for concrete and rebar delivered to the Summit Ridge Apartments project, totaling $24,725.00 due in 30 days.",
        "key_fields": {
            "vendor": "Granite Peak Construction Supply",
            "invoice_number": "INV-48213",
            "total_amount": "$24,725.00",
            "due_date": "2026-07-14",
        },
        "flags": [],
    }

    classify_module = _load_module(
        "classify_handler", os.path.join(ROOT, "lambda", "classify", "handler.py")
    )
    summarize_module = _load_module(
        "summarize_handler", os.path.join(ROOT, "lambda", "summarize", "handler.py")
    )

    event = {
        "bucket": "test-bucket",
        "key": "uploads/invoice_sample.pdf",
        "document_id": str(uuid.uuid4()),
        "extracted_text": SAMPLE_TEXT,
    }

    with patch.object(
        classify_module.bedrock,
        "converse",
        return_value=_fake_converse_response(fake_classification),
    ):
        event = classify_module.handler(event, None)

    assert event["classification"]["document_type"] == "invoice"
    print("Classify step OK:", event["classification"])

    with patch.object(
        summarize_module.bedrock,
        "converse",
        return_value=_fake_converse_response(fake_summary),
    ):
        event = summarize_module.handler(event, None)

    assert "summary" in event
    assert event["summary"]["key_fields"]["invoice_number"] == "INV-48213"
    print("Summarize step OK:", event["summary"])

    print("\nFinal event:")
    print(json.dumps(event, indent=2))


def test_parse_json_response_handles_code_fences():
    """Nova (and most non-Anthropic models) sometimes wrap JSON replies in a
    markdown code fence despite being told not to — this is the safety net
    that keeps the pipeline working when that happens."""
    from json_utils import parse_json_response

    fenced = '```json\n{"document_type": "invoice", "confidence": "high", "reasoning": "x"}\n```'
    parsed = parse_json_response(fenced)
    assert parsed["document_type"] == "invoice"
    print("json_utils code-fence handling OK:", parsed)


if __name__ == "__main__":
    test_classify_and_summarize()
    test_parse_json_response_handles_code_fences()
    print("\nAll local pipeline checks passed.")
