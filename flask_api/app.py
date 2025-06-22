from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.utils import secure_filename
import boto3
import json
from botocore.exceptions import ClientError
import hashlib
import email


# ─── Flask Setup ────────────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# ─── AWS S3 Setup ───────────────────────────────────────────────────────────────
BUCKET_NAME = "smart-resume-bucket-yourname"
credentials_bucket_name = "credential-storage-bucket"
s3_client = boto3.client("s3")

# ─── Routes ─────────────────────────────────────────────────────────────────────
#root url function
@app.route('/')
def hello():
    return "Smart Resume Checker API is live!"

#helper hash function
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# signup endpoint
@app.route('/signup', methods=['POST'])
def signup():
    print("signup started")
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    print("email: ", email, "password", password)
    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    key = f"users/{email}.json"

    # Check if user already exists
    try:
        s3_client.head_object(Bucket=credentials_bucket_name, Key=key)
        return jsonify({"error": "User already exists"}), 409
    except ClientError:
        pass  # Continue if user doesn't exist

    # Store credentials (hashed password)
    user_data = {
        "email": email,
        "password": hash_password(password)
    }

    s3_client.put_object(
        Bucket=credentials_bucket_name,
        Key=key,
        Body=json.dumps(user_data),
        ContentType='application/json'
    )
    print("signup completed")
    return jsonify({"message": "Signup successful!"}), 200

#login end point
@app.route('/login', methods=['POST'])
def login():
    print("login started")
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    print("email: ", email, "password", password)
    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    key = f"users/{email}.json"

    try:
        response = s3_client.get_object(Bucket=credentials_bucket_name, Key=key)
        stored_user = json.loads(response['Body'].read())
    except s3_client.exceptions.ClientError:
        return jsonify({"error": "User does not exist"}), 404

    if stored_user["password"] != hash_password(password):
        return jsonify({"error": "Invalid password"}), 401
    print("login completed")
    return jsonify({"message": "Login successful"}), 200
    

# Step 2: Lambda posts ATS score → store result in results/ folder in S3
@app.route('/receive-score', methods=['POST'])
def receive_score():
    data = request.get_json()
    filename = data.get("filename")
    ats_score = data.get("ats_score")
    matched = data.get("matched_keywords")
    rating = data.get("rating")  
    suggested = data.get("suggested_keywords")  
    email=data.get("email")

    print("email: ", email)
    if not filename or ats_score is None or matched is None:
        return jsonify({"error": "Missing required fields"}), 400

    result_key = f"files/{email}/results/{filename}.json"

    try:
        result_data = {
            "filename": filename,
            "ats_score": ats_score,
            "matched_keywords": matched
        }

        if rating is not None:
            result_data["rating"] = rating

        if suggested is not None:
            result_data["suggested_keywords"] = suggested

        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=result_key,
            Body=json.dumps(result_data),
            ContentType='application/json'
        )

        print(f"✅ Stored ATS result for: {filename}")
        return jsonify({"status": "Result saved"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Manual upload route (used during dev or debugging)
@app.route('/upload-resume', methods=['POST'])
def upload_resume():
    email = request.form.get("email")  # Add this field to your formData in frontend
    if not email or 'file' not in request.files or 'job_description' not in request.form:
        return jsonify({"error": "Email, resume file and job description are required"}), 400

    file = request.files['file']
    job_description = request.form['job_description']

    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    try:
        filename = secure_filename(file.filename)
        s3_resume_key = f"files/{email}/uploads/{filename}"
        s3_jobdesc_key = f"files/{email}/job_descriptions/{filename}.txt"

        # Upload resume PDF
        s3_client.upload_fileobj(file, BUCKET_NAME, s3_resume_key)

        # Upload job description text
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=s3_jobdesc_key,
            Body=job_description,
            ContentType='text/plain'
        )

        return jsonify({
            "message": "Resume and job description uploaded successfully",
            "filename": filename,
            "resume_key": s3_resume_key,
            "jobdesc_key": s3_jobdesc_key
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Step 4: Frontend polls this endpoint to get ATS score
@app.route('/get-ats-score', methods=['GET'])
def get_ats_score():
    filename = request.args.get("filename")
    email= request.args.get("email")
    if not filename:
        return jsonify({"error": "Filename is required"}), 400

    result_key = f"files/{email}/results/{filename}.json"

    try:
        s3_response = s3_client.get_object(Bucket=BUCKET_NAME, Key=result_key)
        content = s3_response['Body'].read().decode('utf-8')
        result_data = json.loads(content)

        # Default fallback if any keys are missing (for backward compatibility)
        ats_score = result_data.get("ats_score")
        matched_keywords = result_data.get("matched_keywords", [])
        suggested_keywords = result_data.get("suggested_keywords", [])
        rating = result_data.get("rating", int((ats_score or 0) / 20))  # fallback rating

        return jsonify({
            "filename": filename,
            "ats_score": ats_score,
            "rating": rating,
            "matched_keywords": matched_keywords,
            "suggested_keywords": suggested_keywords
        })

    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
            return jsonify({"error": f"No ATS result found for {filename}"}), 404
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/list-resumes', methods=['GET'])
def list_resumes():
    print("list resumes started")
    email = request.args.get("email")
    if not email:
        return jsonify({"error": "Email is required"}), 400

    prefix = f"files/{email}/uploads/"
    try:
        response = s3_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=prefix)
        contents = response.get("Contents", [])
        filenames = [obj["Key"].split("/")[-1] for obj in contents]

        print(response)
        print("list resumes completed")
        return jsonify({"resumes": filenames})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/delete-resumes', methods=['POST'])
def delete_resumes():
    print("delete resumes started")
    data = request.get_json()
    email = data.get("email")
    filenames = data.get("filenames", [])

    if not email or not filenames:
        return jsonify({"error": "Email and filenames required"}), 400

    
    try:
        lambda_client = boto3.client('lambda')
        payload = {
            "email": email,
            "filenames": filenames
        }
        print(payload)
        response = lambda_client.invoke(
            FunctionName='delete-resumes',
            InvocationType='Event',
            Payload=json.dumps(payload)
        )
        print(response)
        return jsonify({"message": "Deletion triggered"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    app.run(debug=True)
