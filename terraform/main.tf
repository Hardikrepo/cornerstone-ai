terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

locals {
  name_prefix = "${var.project_name}-${var.environment}"
}

# ---------------------------------------------------------------------------
# S3 bucket — holds uploaded source documents and pipeline results
# ---------------------------------------------------------------------------
resource "aws_s3_bucket" "documents" {
  bucket = "${local.name_prefix}-documents"
  # Set ahead of a teardown so Terraform can empty (including all object
  # versions, since versioning is enabled below) and delete the bucket in
  # one `destroy` — a plain `aws s3 rm --recursive` would leave old
  # versions behind and block deletion.
  force_destroy = true
}

resource "aws_s3_bucket_versioning" "documents" {
  bucket = aws_s3_bucket.documents.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "documents" {
  bucket                  = aws_s3_bucket.documents.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# The bucket itself stays fully private (block_public_access above still
# applies) — this only allows the browser to PUT directly to a presigned
# URL it was handed by the api Lambda, and read back nothing on its own.
# Without this, the frontend's upload step fails with a generic "Failed to
# fetch" (CORS preflight rejection), confirmed against the live deployment.
resource "aws_s3_bucket_cors_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id

  cors_rule {
    allowed_methods = ["PUT"]
    allowed_origins = ["*"]
    allowed_headers = ["*"]
    max_age_seconds = 3000
  }
}

# ---------------------------------------------------------------------------
# Lambda packaging
# ---------------------------------------------------------------------------
data "archive_file" "extract" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/extract"
  output_path = "${path.module}/build/extract.zip"
}

data "archive_file" "classify" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/classify"
  output_path = "${path.module}/build/classify.zip"
}

data "archive_file" "summarize" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/summarize"
  output_path = "${path.module}/build/summarize.zip"
}

# ---------------------------------------------------------------------------
# Lambda functions
# ---------------------------------------------------------------------------
resource "aws_lambda_function" "extract" {
  function_name    = "${local.name_prefix}-extract"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  timeout          = var.textract_timeout_seconds
  filename         = data.archive_file.extract.output_path
  source_code_hash = data.archive_file.extract.output_base64sha256

  environment {
    variables = {
      RESULTS_BUCKET            = aws_s3_bucket.documents.bucket
      TEXTRACT_MAX_POLL_SECONDS = tostring(var.textract_timeout_seconds - 30)
    }
  }
}

resource "aws_lambda_function" "classify" {
  function_name    = "${local.name_prefix}-classify"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  timeout          = var.bedrock_timeout_seconds
  filename         = data.archive_file.classify.output_path
  source_code_hash = data.archive_file.classify.output_base64sha256

  environment {
    variables = {
      BEDROCK_MODEL_ID = var.bedrock_model_id
      AWS_REGION_NAME  = var.aws_region
    }
  }
}

resource "aws_lambda_function" "summarize" {
  function_name    = "${local.name_prefix}-summarize"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  timeout          = var.bedrock_timeout_seconds
  filename         = data.archive_file.summarize.output_path
  source_code_hash = data.archive_file.summarize.output_base64sha256

  environment {
    variables = {
      BEDROCK_MODEL_ID = var.bedrock_model_id
      AWS_REGION_NAME  = var.aws_region
      RESULTS_BUCKET   = aws_s3_bucket.documents.bucket
    }
  }
}

# ---------------------------------------------------------------------------
# Step Functions state machine — Extract -> Classify -> Summarize -> Store
# ---------------------------------------------------------------------------
resource "aws_sfn_state_machine" "pipeline" {
  name     = "${local.name_prefix}-pipeline"
  role_arn = aws_iam_role.sfn_exec.arn

  definition = templatefile("${path.module}/../step_functions/state_machine.asl.json", {
    extract_lambda_arn   = aws_lambda_function.extract.arn
    classify_lambda_arn  = aws_lambda_function.classify.arn
    summarize_lambda_arn = aws_lambda_function.summarize.arn
  })
}
