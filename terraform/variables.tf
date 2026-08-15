variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Prefix used for all resource names"
  type        = string
  default     = "construction-doc-intel"
}

variable "environment" {
  description = "Deployment environment (dev/staging/prod)"
  type        = string
  default     = "dev"
}

variable "bedrock_model_id" {
  description = <<-EOT
    Bedrock model ID used for classification and summarization. Default is
    Amazon Nova Micro via its US cross-region inference profile (cheapest
    text model on Bedrock, ~$0.035/$0.14 per 1M input/output tokens) — note
    the "us." prefix is required: Nova Micro rejects on-demand invocation by
    the bare foundation-model ID ("amazon.nova-micro-v1:0" 400s with
    "Invocation ... with on-demand throughput isn't supported"), confirmed
    against the live API. Swap to an Anthropic Claude model for better
    structured-output reliability and quality — note that requires code
    changes in lambda/classify and lambda/summarize (they call the
    provider-agnostic Bedrock Converse API, not the Anthropic SDK).
  EOT
  type        = string
  default     = "us.amazon.nova-micro-v1:0"
}

variable "bedrock_underlying_regions" {
  description = <<-EOT
    Regions the bedrock_model_id's cross-region inference profile spans, for
    IAM scoping. Invoking an inference profile requires bedrock:InvokeModel
    on the profile ARN AND on the underlying foundation-model ARN in every
    region the profile can route to — not just aws_region. For
    "us.amazon.nova-micro-v1:0" that's us-east-1/us-east-2/us-west-2; check
    `aws bedrock get-inference-profile` if you change bedrock_model_id.
  EOT
  type        = list(string)
  default     = ["us-east-1", "us-east-2", "us-west-2"]
}

variable "textract_timeout_seconds" {
  description = <<-EOT
    Lambda timeout for the Textract extraction step. Must exceed
    TEXTRACT_MAX_POLL_SECONDS (set on the Lambda, default 120s) with buffer
    for cold start and final processing — the extract Lambda polls
    Textract's async job status in-process (start_document_text_detection +
    get_document_text_detection), since detect_document_text (sync) only
    supports single-page documents.
  EOT
  type        = number
  default     = 150
}

variable "bedrock_timeout_seconds" {
  description = "Lambda timeout for Bedrock-calling steps"
  type        = number
  default     = 90
}
