"""API layer fronting the pipeline for the web UI. Behind API Gateway
(HTTP API, payload format 2.0). Three routes, all handled by this one
Lambda:

    POST /documents              -> presigned S3 upload URL + document_id
    POST /documents/{id}/process -> starts the Step Functions execution
    GET  /documents/{id}         -> processing status / final result

Nothing here calls Bedrock or Textract directly — this is pure
orchestration glue between the browser, S3, and the existing pipeline.
"""
import json
import os
import uuid

import boto3

s3 = boto3.client("s3")
sfn = boto3.client("stepfunctions")

DOCUMENTS_BUCKET = os.environ["DOCUMENTS_BUCKET"]
STATE_MACHINE_ARN = os.environ["STATE_MACHINE_ARN"]

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


def _response(status: int, body: dict):
    return {
        "statusCode": status,
        "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    route = event.get("routeKey", "")

    if method == "OPTIONS":
        return _response(200, {})

    if route == "POST /documents":
        return _create_upload_url(event)
    if route == "POST /documents/{id}/process":
        return _start_processing(event)
    if route == "GET /documents/{id}":
        return _get_result(event)

    return _response(404, {"error": f"no handler for route {route!r}"})


def _create_upload_url(event):
    body = json.loads(event.get("body") or "{}")
    filename = body.get("filename", "document.pdf")
    extension = filename.rsplit(".", 1)[-1] if "." in filename else "pdf"
    content_type = body.get("content_type", "application/pdf")

    document_id = str(uuid.uuid4())
    key = f"uploads/{document_id}.{extension}"

    upload_url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": DOCUMENTS_BUCKET, "Key": key, "ContentType": content_type},
        ExpiresIn=300,
    )

    return _response(
        200,
        {"document_id": document_id, "key": key, "upload_url": upload_url},
    )


def _start_processing(event):
    document_id = event["pathParameters"]["id"]
    body = json.loads(event.get("body") or "{}")
    key = body.get("key")
    if not key:
        return _response(400, {"error": "request body must include 'key' from the upload step"})

    execution_name = f"doc-{document_id}"
    execution = sfn.start_execution(
        stateMachineArn=STATE_MACHINE_ARN,
        name=execution_name,
        input=json.dumps({"bucket": DOCUMENTS_BUCKET, "key": key, "document_id": document_id}),
    )

    # Pointer file so GET /documents/{id} can find the execution before the
    # pipeline has written a results/{id}.json.
    s3.put_object(
        Bucket=DOCUMENTS_BUCKET,
        Key=f"executions/{document_id}.json",
        Body=json.dumps({"execution_arn": execution["executionArn"]}).encode("utf-8"),
        ContentType="application/json",
    )

    return _response(
        202,
        {"document_id": document_id, "execution_arn": execution["executionArn"], "status": "started"},
    )


def _get_result(event):
    document_id = event["pathParameters"]["id"]

    try:
        obj = s3.get_object(Bucket=DOCUMENTS_BUCKET, Key=f"results/{document_id}.json")
        result = json.loads(obj["Body"].read())
        return _response(200, {"status": "complete", "result": result})
    except s3.exceptions.NoSuchKey:
        pass

    try:
        pointer = s3.get_object(Bucket=DOCUMENTS_BUCKET, Key=f"executions/{document_id}.json")
    except s3.exceptions.NoSuchKey:
        return _response(404, {"status": "not_found"})

    execution_arn = json.loads(pointer["Body"].read())["execution_arn"]
    description = sfn.describe_execution(executionArn=execution_arn)
    sfn_status = description["status"]

    if sfn_status == "FAILED":
        return _response(200, {"status": "failed", "cause": description.get("cause", "unknown error")})
    if sfn_status in ("TIMED_OUT", "ABORTED"):
        return _response(200, {"status": "failed", "cause": sfn_status})

    return _response(
        200,
        {"status": "processing", "execution_status": sfn_status, "current_step": _current_step(execution_arn)},
    )


def _current_step(execution_arn: str) -> str:
    """Returns the name of the state currently running, by reading recent
    execution history (newest first) for the last "StateEntered" event.
    Lets the UI show real step-by-step progress instead of a generic
    spinner — no fabricated progress, just what Step Functions reports.
    Falls back to "Extract" (the first state) if history isn't available
    yet, which happens briefly right after StartExecution.
    """
    try:
        history = sfn.get_execution_history(
            executionArn=execution_arn, maxResults=10, reverseOrder=True
        )
    except Exception:
        return "Extract"

    for evt in history.get("events", []):
        if evt["type"] == "TaskStateEntered":
            return evt["stateEnteredEventDetails"]["name"]

    return "Extract"
