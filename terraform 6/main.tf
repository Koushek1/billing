# Configure AWS Provider
provider "aws" {
  region = "us-west-2"
}

# Variables
variable "environment" {
  description = "Environment name"
  default     = "prod"
}

# S3 Bucket for hosting the static website
resource "aws_s3_bucket" "billing_website" {
  bucket = "aws-billing-dashboard-${random_string.suffix.result}"
}

resource "random_string" "suffix" {
  length  = 8
  special = false
  upper   = false
}

# Disable block public access settings for the bucket
resource "aws_s3_bucket_public_access_block" "billing_website" {
  bucket = aws_s3_bucket.billing_website.id

  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

# Enable website hosting on the S3 bucket
resource "aws_s3_bucket_website_configuration" "billing_website" {
  bucket = aws_s3_bucket.billing_website.id

  index_document {
    suffix = "index.html"
  }

  error_document {
    key = "error.html"
  }
}

# S3 bucket ownership controls
resource "aws_s3_bucket_ownership_controls" "billing_website" {
  bucket = aws_s3_bucket.billing_website.id
  rule {
    object_ownership = "BucketOwnerPreferred"
  }
}

# S3 bucket ACL
resource "aws_s3_bucket_acl" "billing_website" {
  depends_on = [
    aws_s3_bucket_ownership_controls.billing_website,
    aws_s3_bucket_public_access_block.billing_website,
  ]

  bucket = aws_s3_bucket.billing_website.id
  acl    = "public-read"
}

# S3 bucket policy to allow public access to the website
resource "aws_s3_bucket_policy" "billing_website" {
  depends_on = [
    aws_s3_bucket_public_access_block.billing_website
  ]
  
  bucket = aws_s3_bucket.billing_website.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "PublicReadGetObject"
        Effect    = "Allow"
        Principal = "*"
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.billing_website.arn}/*"
      },
    ]
  })
}

# IAM role for Lambda
resource "aws_iam_role" "lambda_role" {
  name = "billing_lambda_role_${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

# IAM policy for accessing Cost Explorer and other services
resource "aws_iam_role_policy" "lambda_policy" {
  name = "billing_lambda_policy"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ce:GetCostAndUsage",
          "ce:GetCostForecast",
          "ce:GetUsageForecast",
          "ce:GetReservationUtilization",
          "ce:GetReservationCoverage",
          "ce:GetDimensionValues",
          "ce:GetTags",
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "s3:PutObject",
          "s3:PutObjectAcl",
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = "*"
      }
    ]
  })
}
# Lambda function
resource "aws_lambda_function" "billing_lambda" {
  filename         = "billing_lambda.zip"
  function_name    = "fetch_billing_data_${var.environment}"
  role            = aws_iam_role.lambda_role.arn
  handler         = "billing_lambda.handler"
  runtime         = "python3.9"
  timeout         = 30
  memory_size     = 256

  environment {
    variables = {
      S3_BUCKET = aws_s3_bucket.billing_website.id
      ENVIRONMENT = var.environment
    }
  }
}

# CloudWatch Log Group for Lambda
resource "aws_cloudwatch_log_group" "lambda_logs" {
  name              = "/aws/lambda/${aws_lambda_function.billing_lambda.function_name}"
  retention_in_days = 14
}

# API Gateway
resource "aws_apigatewayv2_api" "billing_api" {
  name          = "billing-api-${var.environment}"
  protocol_type = "HTTP"
  
  cors_configuration {
    allow_origins = ["*"]
    allow_methods = ["GET", "OPTIONS"]
    allow_headers = ["Content-Type", "Authorization"]
    max_age      = 300
  }
}

# API Gateway Stage
resource "aws_apigatewayv2_stage" "billing_stage" {
  api_id = aws_apigatewayv2_api.billing_api.id
  name   = var.environment
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_logs.arn
    format = jsonencode({
      requestId          = "$context.requestId"
      ip                = "$context.identity.sourceIp"
      requestTime       = "$context.requestTime"
      httpMethod        = "$context.httpMethod"
      routeKey          = "$context.routeKey"
      status           = "$context.status"
      protocol         = "$context.protocol"
      responseLength   = "$context.responseLength"
      integrationError = "$context.integrationErrorMessage"
    })
  }
}

# CloudWatch Log Group for API Gateway
resource "aws_cloudwatch_log_group" "api_logs" {
  name              = "/aws/apigateway/${aws_apigatewayv2_api.billing_api.name}"
  retention_in_days = 14
}

# API Gateway Integration
resource "aws_apigatewayv2_integration" "lambda_integration" {
  api_id           = aws_apigatewayv2_api.billing_api.id
  integration_type = "AWS_PROXY"
  integration_uri  = aws_lambda_function.billing_lambda.invoke_arn
  
  integration_method = "POST"
  payload_format_version = "2.0"
}

# API Gateway Route
resource "aws_apigatewayv2_route" "billing_route" {
  api_id    = aws_apigatewayv2_api.billing_api.id
  route_key = "GET /billing"
  target    = "integrations/${aws_apigatewayv2_integration.lambda_integration.id}"
}

# Lambda permission for API Gateway
resource "aws_lambda_permission" "api_gw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.billing_lambda.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.billing_api.execution_arn}/*/*"
}

# Outputs
output "website_endpoint" {
  value = "http://${aws_s3_bucket_website_configuration.billing_website.website_endpoint}"
}

output "api_endpoint" {
  value = "${aws_apigatewayv2_stage.billing_stage.invoke_url}/billing"
}

output "s3_bucket_name" {
  value = aws_s3_bucket.billing_website.id
}