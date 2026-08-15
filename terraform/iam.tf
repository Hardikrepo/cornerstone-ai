data "aws_caller_identity" "current" {}

locals {
  # Cross-region inference profile IDs are prefixed with the routing scope
  # ("us.", "eu.", etc.) — strip it to get the bare foundation-model ID used
  # in the underlying per-region model ARNs. If bedrock_model_id is changed
  # to a model invoked directly (no inference profile), this is a no-op.
  bedrock_base_model_id = trimprefix(var.bedrock_model_id, "us.")
}

# ---------------------------------------------------------------------------
# Lambda execution role — shared by extract/classify/summarize
# ---------------------------------------------------------------------------
resource "aws_iam_role" "lambda_exec" {
  name = "${local.name_prefix}-lambda-exec"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic_logs" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_s3_access" {
  name = "${local.name_prefix}-lambda-s3"
  role = aws_iam_role.lambda_exec.id

  # s3:ListBucket is required on the bucket ARN itself (not just object
  # access) so a GetObject on a not-yet-created key returns a real 404
  # NoSuchKey instead of AccessDenied — without it, S3 can't tell the caller
  # apart from someone probing for the object's existence and refuses to
  # say either way. Confirmed against the live deployment: the api Lambda's
  # /documents/{id} status check crashed on this exact gap before results/
  # existed for a document.
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject"
        ]
        Resource = "${aws_s3_bucket.documents.arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.documents.arn
      }
    ]
  })
}

resource "aws_iam_role_policy" "lambda_textract_access" {
  name = "${local.name_prefix}-lambda-textract"
  role = aws_iam_role.lambda_exec.id

  # Async actions (Start/Get*DocumentTextDetection) — the extract Lambda
  # uses these, not the sync DetectDocumentText/AnalyzeDocument, because the
  # sync API only supports single-page documents (confirmed against the
  # live pipeline: a real 2-page PDF hit UnsupportedDocumentException there).
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "textract:StartDocumentTextDetection",
        "textract:GetDocumentTextDetection"
      ]
      Resource = "*"
    }]
  })
}

resource "aws_iam_role_policy" "lambda_bedrock_access" {
  name = "${local.name_prefix}-lambda-bedrock"
  role = aws_iam_role.lambda_exec.id

  # Invoking a cross-region inference profile (the default bedrock_model_id)
  # requires bedrock:InvokeModel on BOTH the inference-profile ARN AND the
  # underlying foundation-model ARN in every region the profile can route
  # to — confirmed against the live API; the profile-only grant alone gets
  # AccessDenied. Still scoped to this one model/profile, not every model in
  # the account.
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "bedrock:InvokeModel"
      ]
      Resource = concat(
        ["arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:inference-profile/${var.bedrock_model_id}"],
        [for region in var.bedrock_underlying_regions :
          "arn:aws:bedrock:${region}::foundation-model/${local.bedrock_base_model_id}"
        ]
      )
    }]
  })
}

resource "aws_iam_role_policy" "lambda_stepfunctions_access" {
  name = "${local.name_prefix}-lambda-sfn"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "states:StartExecution",
        "states:DescribeExecution",
        "states:GetExecutionHistory"
      ]
      # DescribeExecution needs the execution ARN, not just the state
      # machine ARN — executions inherit the state machine's ARN prefix.
      Resource = [
        aws_sfn_state_machine.pipeline.arn,
        "arn:aws:states:${var.aws_region}:*:execution:${aws_sfn_state_machine.pipeline.name}:*"
      ]
    }]
  })
}

# ---------------------------------------------------------------------------
# Step Functions execution role
# ---------------------------------------------------------------------------
resource "aws_iam_role" "sfn_exec" {
  name = "${local.name_prefix}-sfn-exec"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "states.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "sfn_invoke_lambdas" {
  name = "${local.name_prefix}-sfn-invoke"
  role = aws_iam_role.sfn_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "lambda:InvokeFunction"
      Resource = [
        aws_lambda_function.extract.arn,
        aws_lambda_function.classify.arn,
        aws_lambda_function.summarize.arn
      ]
    }]
  })
}
