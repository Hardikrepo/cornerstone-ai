"""Classification step: labels the extracted text as a construction document type.

Input event (chained from the Extract step):
    {"bucket": ..., "key": ..., "document_id": ..., "extracted_text": "..."}

Output: input event plus a "classification" object:
    {"document_type": "invoice", "confidence": "high", "reasoning": "..."}

Uses the Bedrock Converse API (provider-agnostic) rather than the Anthropic
SDK, so this works against Amazon Nova, Meta Llama, Mistral, etc. — whatever
BEDROCK_MODEL_ID points at. Trade-off: unlike Claude's structured-outputs
feature, there's no schema-enforced response here, so the model is
instructed to return raw JSON and the response is parsed defensively (see
parse_json_response.py). A malformed response raises, which the Step
Functions Retry on this state already handles.
"""
import json
import os

import boto3

from json_utils import parse_json_response

MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "amazon.nova-micro-v1:0")

DOCUMENT_TYPES = [
    "invoice",
    "permit",
    "change_order",
    "rfi",
    "submittal",
    "other",
]

bedrock = boto3.client("bedrock-runtime")


def handler(event, context):
    extracted_text = event["extracted_text"]

    prompt = (
        "Classify the following construction industry document.\n\n"
        f"Choose exactly one document_type from this set: {', '.join(DOCUMENT_TYPES)}.\n\n"
        "Respond with ONLY a single JSON object, no markdown code fences, no "
        "explanation before or after it, matching exactly this shape:\n"
        '{"document_type": "<one of the allowed values>", '
        '"confidence": "high|medium|low", '
        '"reasoning": "<one sentence explaining the classification>"}\n\n'
        f"--- DOCUMENT TEXT ---\n{extracted_text}"
    )

    response = bedrock.converse(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 512, "temperature": 0},
    )

    text = response["output"]["message"]["content"][0]["text"]
    classification = parse_json_response(text)

    if classification.get("document_type") not in DOCUMENT_TYPES:
        raise ValueError(f"Model returned an unrecognized document_type: {classification!r}")

    event["classification"] = classification
    return event
