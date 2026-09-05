# S3 bucket for incident-classification training datasets, collected from
# multiple sources (see ai-agents-suite/scripts/collect_datasets.py):
#   - servicenow-incidents/   real incidents exported live from ServiceNow
#   - infra-incidents/        real K8s-origin incidents from infra-monitor
#   - synthetic-training-data/ a broader, hand-authored synthetic set
#                              covering categories real data doesn't have
#                              enough volume in yet (same gap noted in
#                              predictive-intelligence-agent's own code:
#                              no historical labeled ticket volume to train
#                              a real model on).
resource "aws_s3_bucket" "datasets" {
  bucket = "${var.project_name}-incident-datasets"
  tags   = var.tags
}

resource "aws_s3_bucket_versioning" "datasets" {
  bucket = aws_s3_bucket.datasets.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "datasets" {
  bucket                  = aws_s3_bucket.datasets.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "datasets" {
  bucket = aws_s3_bucket.datasets.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

output "datasets_bucket" {
  value = aws_s3_bucket.datasets.bucket
}
