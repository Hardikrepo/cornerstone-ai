"""Exercises the api Lambda's three routes locally with mocked boto3 clients
(S3 + Step Functions) — no AWS credentials or deployment needed.

Run:
    pip install boto3
    python tests/test_api_handler.py
"""
import importlib.util
import json
import os
import sys
from unittest.mock import MagicMock, patch

os.environ.setdefault("DOCUMENTS_BUCKET", "test-documents-bucket")
os.environ.setdefault(
    "STATE_MACHINE_ARN",
    "arn:aws:states:us-east-1:123456789012:stateMachine:test-pipeline",
)

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _load_module(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _api_gw_event(method: str, route_key: str, path_params=None, body=None):
    return {
        "routeKey": route_key,
        "requestContext": {"http": {"method": method}},
        "pathParameters": path_params or {},
        "body": json.dumps(body) if body is not None else None,
    }


def test_create_upload_url():
    api = _load_module("api_handler", os.path.join(ROOT, "lambda", "api", "handler.py"))
    api.s3.generate_presigned_url = MagicMock(return_value="https://s3.example/presigned")

    event = _api_gw_event("POST", "POST /documents", body={"filename": "invoice.pdf"})
    response = api.handler(event, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["upload_url"] == "https://s3.example/presigned"
    assert body["key"].endswith(".pdf")
    assert body["document_id"] in body["key"]
    print("POST /documents OK:", body)


def test_start_processing():
    api = _load_module("api_handler_2", os.path.join(ROOT, "lambda", "api", "handler.py"))
    api.sfn.start_execution = MagicMock(
        return_value={"executionArn": "arn:aws:states:us-east-1:123456789012:execution:test-pipeline:doc-abc"}
    )
    api.s3.put_object = MagicMock()

    event = _api_gw_event(
        "POST",
        "POST /documents/{id}/process",
        path_params={"id": "abc-123"},
        body={"key": "uploads/abc-123.pdf"},
    )
    response = api.handler(event, None)

    assert response["statusCode"] == 202
    body = json.loads(response["body"])
    assert body["status"] == "started"
    api.s3.put_object.assert_called_once()
    print("POST /documents/{id}/process OK:", body)


def test_get_result_complete():
    api = _load_module("api_handler_3", os.path.join(ROOT, "lambda", "api", "handler.py"))

    fake_result = {
        "document_id": "abc-123",
        "classification": {"document_type": "invoice", "confidence": "high"},
        "summary": {"summary": "...", "key_fields": {}, "flags": []},
        "review_status": "pending_human_review",
    }

    class FakeBody:
        def read(self_inner):
            return json.dumps(fake_result).encode("utf-8")

    api.s3.get_object = MagicMock(return_value={"Body": FakeBody()})

    event = _api_gw_event("GET", "GET /documents/{id}", path_params={"id": "abc-123"})
    response = api.handler(event, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["status"] == "complete"
    assert body["result"]["classification"]["document_type"] == "invoice"
    print("GET /documents/{id} (complete) OK:", body["status"])


def test_get_result_still_processing():
    api = _load_module("api_handler_4", os.path.join(ROOT, "lambda", "api", "handler.py"))

    # First call (results/{id}.json) raises NoSuchKey; second call
    # (executions/{id}.json) succeeds with the execution pointer.
    class NoSuchKey(Exception):
        pass

    # boto3 client's `.exceptions` is a read-only property on the real
    # client — swap the whole client for a mock so we can attach a fake
    # exceptions namespace.
    api.s3 = MagicMock()
    api.s3.exceptions.NoSuchKey = NoSuchKey

    class FakePointerBody:
        def read(self_inner):
            return json.dumps({"execution_arn": "arn:aws:states:us-east-1:123456789012:execution:x:y"}).encode(
                "utf-8"
            )

    def fake_get_object(Bucket, Key):
        if Key.startswith("results/"):
            raise NoSuchKey()
        return {"Body": FakePointerBody()}

    api.s3.get_object = MagicMock(side_effect=fake_get_object)
    api.sfn.describe_execution = MagicMock(return_value={"status": "RUNNING"})
    api.sfn.get_execution_history = MagicMock(
        return_value={
            "events": [
                {"type": "TaskStateEntered", "stateEnteredEventDetails": {"name": "Classify"}},
                {"type": "TaskStateExited", "stateExitedEventDetails": {"name": "Extract"}},
            ]
        }
    )

    event = _api_gw_event("GET", "GET /documents/{id}", path_params={"id": "abc-123"})
    response = api.handler(event, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["status"] == "processing"
    assert body["current_step"] == "Classify"
    print("GET /documents/{id} (processing) OK:", body)


if __name__ == "__main__":
    test_create_upload_url()
    test_start_processing()
    test_get_result_complete()
    test_get_result_still_processing()
    print("\nAll API handler checks passed.")
