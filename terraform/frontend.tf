# ---------------------------------------------------------------------------
# Static frontend — S3 static website hosting
# ---------------------------------------------------------------------------
resource "aws_s3_bucket" "frontend" {
  bucket        = "${local.name_prefix}-frontend"
  force_destroy = true # allows a clean `terraform destroy` without manual emptying
}

resource "aws_s3_bucket_website_configuration" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  index_document {
    suffix = "index.html"
  }
}

# Static site hosting requires public read — scoped to this bucket only,
# separate from the private "documents" bucket above.
resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket                  = aws_s3_bucket.frontend.id
  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

resource "aws_s3_bucket_policy" "frontend_public_read" {
  bucket     = aws_s3_bucket.frontend.id
  depends_on = [aws_s3_bucket_public_access_block.frontend]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "PublicReadGetObject"
      Effect    = "Allow"
      Principal = "*"
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.frontend.arn}/*"
    }]
  })
}

locals {
  frontend_dir = "${path.module}/../frontend"
}

resource "aws_s3_object" "frontend_index" {
  bucket       = aws_s3_bucket.frontend.id
  key          = "index.html"
  source       = "${local.frontend_dir}/index.html"
  etag         = filemd5("${local.frontend_dir}/index.html")
  content_type = "text/html"
}

resource "aws_s3_object" "frontend_app" {
  bucket       = aws_s3_bucket.frontend.id
  key          = "app.js"
  source       = "${local.frontend_dir}/app.js"
  etag         = filemd5("${local.frontend_dir}/app.js")
  content_type = "application/javascript"
}

resource "aws_s3_object" "frontend_style" {
  bucket       = aws_s3_bucket.frontend.id
  key          = "style.css"
  source       = "${local.frontend_dir}/style.css"
  etag         = filemd5("${local.frontend_dir}/style.css")
  content_type = "text/css"
}

# config.js is generated from the template with the real API Gateway URL —
# this is what makes the deployed frontend "just work" with no manual step.
resource "aws_s3_object" "frontend_config" {
  bucket       = aws_s3_bucket.frontend.id
  key          = "config.js"
  content_type = "application/javascript"
  content = templatefile("${local.frontend_dir}/config.template.js", {
    api_base_url = aws_apigatewayv2_stage.default.invoke_url
  })
}
