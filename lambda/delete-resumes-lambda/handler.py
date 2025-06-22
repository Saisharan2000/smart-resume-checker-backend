import boto3
import os

s3 = boto3.client("s3")
BUCKET = "smart-resume-bucket-yourname"
 

def lambda_handler(event, context):
    email = event.get("email")
    filenames = event.get("filenames", [])
    prefix_resume = f"files/{email}/uploads/"
    prefix_JobDescription = f"files/{email}/job_descriptions/"
    prefix_result = f"files/{email}/results/"

    for fname in filenames:
        key_resume = f"{prefix_resume}{fname}"
        key_JobDescription = f"{prefix_JobDescription}{fname}.txt"
        key_result = f"{prefix_result}{fname}.json"
        try:
            s3.delete_object(Bucket=BUCKET, Key=key_resume)
            s3.delete_object(Bucket=BUCKET, Key=key_JobDescription)
            s3.delete_object(Bucket=BUCKET, Key=key_result)
            print(f"✅ Deleted: {key_resume, key_JobDescription}")
        except Exception as e:
            print(f"❌ Failed to delete {key}: {str(e)}")

    return {"status": "completed", "deleted": len(filenames)}
