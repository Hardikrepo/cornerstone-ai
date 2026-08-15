"""Extraction step: pulls raw text out of a document in S3 via Amazon Textract.

Input event (from Step Functions):
    {"bucket": "<s3-bucket>", "key": "uploads/<document_id>.pdf", "document_id": "..."}

`document_id` is optional on input — the API layer assigns it at upload time
so it can be used to look up results later, but a direct/manual invocation
(e.g. via `start-execution`) still works without one.

Output:
    {"bucket": ..., "key": ..., "document_id": ..., "extracted_text": "..."}

Uses Textract's ASYNC API (start_document_text_detection +
get_document_text_detection), not the synchronous detect_document_text.
detect_document_text only supports single-page documents — a real 2-page
PDF hit `UnsupportedDocumentException: Request has unsupported document
format` against the live pipeline, confirmed via CloudWatch logs, which is
what motivated this rewrite. The async API supports multi-page PDF/TIFF.
"""
import os
import time
import uuid

import boto3

textract = boto3.client("textract")

POLL_INTERVAL_SECONDS = 2
# Must stay comfortably under the Lambda's own timeout (see
# textract_timeout_seconds in terraform/variables.tf) so we raise our own
# clear TimeoutError instead of the Lambda runtime hard-killing mid-poll.
MAX_POLL_SECONDS = int(os.environ.get("TEXTRACT_MAX_POLL_SECONDS", "120"))


def handler(event, context):
    bucket = event["bucket"]
    key = event["key"]
    document_id = event.get("document_id") or str(uuid.uuid4())

    job_id = textract.start_document_text_detection(
        DocumentLocation={"S3Object": {"Bucket": bucket, "Name": key}}
    )["JobId"]

    extracted_text = _wait_for_job_and_collect_text(job_id)

    return {
        "bucket": bucket,
        "key": key,
        "document_id": document_id,
        "extracted_text": extracted_text,
    }


def _wait_for_job_and_collect_text(job_id: str) -> str:
    deadline = time.monotonic() + MAX_POLL_SECONDS

    while True:
        response = textract.get_document_text_detection(JobId=job_id)
        status = response["JobStatus"]

        if status == "SUCCEEDED":
            return _collect_all_lines(job_id, response)
        if status == "FAILED":
            raise RuntimeError(
                f"Textract job {job_id} failed: {response.get('StatusMessage', 'no message')}"
            )
        if time.monotonic() > deadline:
            raise TimeoutError(f"Textract job {job_id} did not complete within {MAX_POLL_SECONDS}s")

        time.sleep(POLL_INTERVAL_SECONDS)


def _collect_all_lines(job_id: str, first_page: dict) -> str:
    """Textract paginates results (NextToken) for larger documents — walk
    every page so multi-page extractions aren't silently truncated."""
    lines = [b["Text"] for b in first_page.get("Blocks", []) if b["BlockType"] == "LINE"]

    next_token = first_page.get("NextToken")
    while next_token:
        page = textract.get_document_text_detection(JobId=job_id, NextToken=next_token)
        lines.extend(b["Text"] for b in page.get("Blocks", []) if b["BlockType"] == "LINE")
        next_token = page.get("NextToken")

    return "\n".join(lines)
