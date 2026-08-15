"""Summarization step: produces a human-readable summary + key structured
fields for the document, then writes the final combined result to S3.

Input event (chained from the Classify step):
    {"bucket": ..., "key": ..., "document_id": ..., "extracted_text": ...,
     "classification": {...}}

Output: input event plus "summary" and "result_key" (S3 location of the
final combined JSON, ready for the human-review step of a later phase).

Uses the Bedrock Converse API (provider-agnostic) rather than the Anthropic
SDK — see the note in classify/handler.py for why, and json_utils.py for how
the model's JSON response is parsed defensively.
"""
import json
import os

import boto3

from json_utils import parse_json_response

MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "amazon.nova-micro-v1:0")
RESULTS_BUCKET = os.environ.get("RESULTS_BUCKET")

bedrock = boto3.client("bedrock-runtime")
s3 = boto3.client("s3")


def handler(event, context):
    extracted_text = event["extracted_text"]
    classification = event["classification"]

    prompt = (
        f"This construction industry document was classified as: "
        f"{classification['document_type']}.\n\n"
        "Summarize it and extract the key structured fields a construction "
        "marketing/ops reviewer would need, and flag anything that looks "
        "incomplete or inconsistent.\n\n"
        "Respond with ONLY a single JSON object, no markdown code fences, no "
        "explanation before or after it, matching exactly this shape:\n"
        '{"summary": "<2-4 sentence plain-language summary>", '
        '"key_fields": {"<field name>": "<value>", ...}, '
        '"flags": ["<anything worth a human reviewer\'s attention>", ...]}\n'
        'key_fields and flags may be empty ({} / []) if nothing applies. '
        "key_fields might include things like vendor, total_amount, "
        "permit_number, issue_date — whichever apply to this document type.\n\n"
        f"--- DOCUMENT TEXT ---\n{extracted_text}"
    )

    response = bedrock.converse(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 1024, "temperature": 0},
    )

    text = response["output"]["message"]["content"][0]["text"]
    summary = parse_json_response(text)

    for required_key in ("summary", "key_fields", "flags"):
        if required_key not in summary:
            raise ValueError(f"Model response missing required key {required_key!r}: {summary!r}")

    result = {
        "document_id": event["document_id"],
        "source_bucket": event["bucket"],
        "source_key": event["key"],
        "classification": classification,
        "summary": summary,
        "review_status": "pending_human_review",
    }

    result_key = f"results/{event['document_id']}.json"
    if RESULTS_BUCKET:
        s3.put_object(
            Bucket=RESULTS_BUCKET,
            Key=result_key,
            Body=json.dumps(result, indent=2).encode("utf-8"),
            ContentType="application/json",
        )

    event["summary"] = summary
    event["result_key"] = result_key
    return event
