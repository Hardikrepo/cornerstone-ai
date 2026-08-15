output "documents_bucket" {
  description = "S3 bucket holding uploaded documents and pipeline results"
  value       = aws_s3_bucket.documents.bucket
}

output "state_machine_arn" {
  description = "ARN of the Step Functions pipeline"
  value       = aws_sfn_state_machine.pipeline.arn
}

output "extract_lambda_name" {
  value = aws_lambda_function.extract.function_name
}

output "classify_lambda_name" {
  value = aws_lambda_function.classify.function_name
}

output "summarize_lambda_name" {
  value = aws_lambda_function.summarize.function_name
}

output "api_base_url" {
  description = "Base URL of the API Gateway HTTP API fronting the pipeline"
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "frontend_url" {
  description = "S3 static website URL for the web UI"
  value       = aws_s3_bucket_website_configuration.frontend.website_endpoint
}
