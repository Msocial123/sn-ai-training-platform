#!/usr/bin/env bash
# Runs the dataset collector and uploads everything to S3.
#
# Usage:
#   export SERVICENOW_INSTANCE_URL=https://yourinstance.service-now.com
#   export SERVICENOW_CLIENT_ID=...
#   export SERVICENOW_CLIENT_SECRET=...
#   export AWS_PROFILE=sn-training   # or whatever your AWS CLI profile is
#   bash collect_and_upload.sh <bucket-name>
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

BUCKET="${1:?Usage: bash collect_and_upload.sh <bucket-name>}"
OUT_DIR="./collected"

echo "==> Collecting datasets"
python generate_synthetic_dataset.py > synthetic_incidents.json
python collect_datasets.py "$OUT_DIR"

echo ""
echo "==> Uploading to s3://$BUCKET/"
aws s3 cp "$OUT_DIR/synthetic-incidents.json" "s3://$BUCKET/synthetic-training-data/synthetic-incidents.json"
[ -f "$OUT_DIR/sample-tickets.json" ] && aws s3 cp "$OUT_DIR/sample-tickets.json" "s3://$BUCKET/synthetic-training-data/sample-tickets.json"
[ -f "$OUT_DIR/servicenow-incidents.json" ] && aws s3 cp "$OUT_DIR/servicenow-incidents.json" "s3://$BUCKET/servicenow-incidents/$(date +%Y-%m-%d)-export.json"

echo ""
echo "==> Done. Contents of s3://$BUCKET/:"
aws s3 ls "s3://$BUCKET/" --recursive --human-readable
