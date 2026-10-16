import { S3Client } from "@aws-sdk/client-s3";

// The app's own S3 bucket. The client reads the endpoint, region and keys from
// the AWS_* variables Freepod sets (in App Studio: eval "$(dev-s3)"), so none
// of them belong in code.
export const s3 = new S3Client({ forcePathStyle: true });
export const bucket = process.env.S3_BUCKET ?? "";
