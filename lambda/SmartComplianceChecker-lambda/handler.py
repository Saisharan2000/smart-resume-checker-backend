import json
import boto3
import re
import urllib.request
import traceback
from urllib.parse import unquote_plus

s3 = boto3.client('s3')
textract = boto3.client('textract')

FLASK_API_URL = "https://mosjf1wu16.execute-api.ap-south-1.amazonaws.com/dev/receive-score"

TECH_KEYWORDS = set([
  "Java", "Python", "Node.js", "Django", "Flask", "Spring", "Express.js",
  "Ruby on Rails", "Go", "C#", ".NET", "REST", "GraphQL", "gRPC",
  "Microservices", "API", "Postman", "MVC", "Kotlin",
  "HTML", "CSS", "JavaScript", "TypeScript", "React", "Angular", "Vue.js",
  "Next.js", "Redux", "SASS", "Bootstrap", "Tailwind", "jQuery",
  "Web Components", "AJAX", "DOM", "Material UI", "Three.js",
  "SQL", "MySQL", "PostgreSQL", "MongoDB", "Redis", "Oracle", "SQLite",
  "Cassandra", "Elasticsearch", "Firebase", "DynamoDB", "BigQuery", "InfluxDB",
  "Machine Learning", "Deep Learning", "TensorFlow", "PyTorch", "Keras",
  "Scikit-learn", "Pandas", "NumPy", "OpenCV", "NLP", "Hugging Face",
  "BERT", "LSTM", "XGBoost", "Data Science", "Computer Vision", "Prompt Engineering",
  "Docker", "Kubernetes", "AWS", "GCP", "Azure", "CI/CD", "Jenkins",
  "GitHub Actions", "Terraform", "Ansible", "Prometheus", "Grafana",
  "CloudFormation", "Helm", "S3", "EC2", "Lambda", "CloudWatch",
  "Git", "GitHub", "Bitbucket", "VSCode", "JIRA", "Agile", "Scrum",
  "Linux", "Bash", "Slack", "Notion", "Trello", "Figma",
  "Design Patterns", "OOP"
])  # your full keyword list here (unchanged)


def extract_keywords(text):
    words = re.findall(r'\b[A-Za-z][A-Za-z0-9.+#-]{2,}\b', text)
    return set(word.strip() for word in words)


def extract_text_from_s3(bucket, key):
    try:
        print(f"🔍 Extracting text using Textract from s3://{bucket}/{key}")
        response = textract.detect_document_text(
            Document={'S3Object': {'Bucket': bucket, 'Name': key}}
        )
        print("✅ Text extracted successfully!")
        lines = [block['Text'] for block in response['Blocks'] if block['BlockType'] == 'LINE']
        return "\n".join(lines)
    except Exception as e:
        print("❌ Failed to extract text using Textract.")
        traceback.print_exc()
        raise

def get_job_description(bucket, filename, email_folder):
    jd_key = f"files/{email_folder}/job_descriptions/{filename}.txt"
    try:
        print(f"📄 Loading JD from s3://{bucket}/{jd_key}")
        response = s3.get_object(Bucket=bucket, Key=jd_key)
        return response['Body'].read().decode('utf-8')
    except Exception as e:
        print("❌ Failed to load JD file.")
        traceback.print_exc()
        raise

def calculate_ats_score(resume_text, jd_text):
    resume_set = {w.lower() for w in extract_keywords(resume_text)}
    jd_set = {w.lower() for w in extract_keywords(jd_text)}
    tech_keywords_lower = {kw.lower() for kw in TECH_KEYWORDS}

    jd_tech_keywords = jd_set.intersection(tech_keywords_lower)
    matched_keywords = list(jd_tech_keywords.intersection(resume_set))
    missing_keywords = list(jd_tech_keywords.difference(resume_set))

    score = int((len(matched_keywords) / len(jd_tech_keywords)) * 100) if jd_tech_keywords else 0
    stars = min(5, max(1, round(score / 20)))

    print("✅ JD keywords:", jd_set)
    print("✅ Resume keywords:", resume_set)
    print("✅ JD Tech Keywords:", jd_tech_keywords)
    print("✅ Matched:", matched_keywords)
    print("✅ Missing:", missing_keywords)

    return score, matched_keywords, missing_keywords, stars





def lambda_handler(event, context):
    print("✅ Lambda triggered!")

    try:
        record = event['Records'][0]
        bucket = record['s3']['bucket']['name']
        raw_key = record['s3']['object']['key']
        key = unquote_plus(raw_key)
        filename = key.rsplit('/', 1)[-1]
        email_folder = key.split('/')[1]

        print(f"📥 Processing: s3://{bucket}/{key} (filename: {filename})")

        resume_text = extract_text_from_s3(bucket, key)
        jd_text = get_job_description(bucket, filename, email_folder)

        ats_score, matched_keywords, suggested_keywords, stars = calculate_ats_score(resume_text, jd_text)

        result_data = {
            "filename": filename,
            "ats_score": ats_score,
            "rating": stars,
            "matched_keywords": matched_keywords,
            "suggested_keywords": suggested_keywords,
            "email" : email_folder
        }

        try:
            data = json.dumps(result_data).encode("utf-8")
            req = urllib.request.Request(FLASK_API_URL, data=data, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req) as response:
                resp_body = response.read().decode()
                print(f"🚀 Posted to Flask API: {response.status}")
                print(f"📥 Flask response: {resp_body}")
        except Exception as post_err:
            print(f"❌ Flask API post failed: {str(post_err)}")
            traceback.print_exc()
            print("💾 Saving result directly to S3 as fallback...")
            s3.put_object(
                Bucket=bucket,
                Key=f"results/{filename}.json",
                Body=json.dumps(result_data),
                ContentType='application/json'
            )
            print(f"✅ Fallback saved to s3://{bucket}/results/{filename}.json")

        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'Processing complete'})
        }

    except Exception as e:
        print("❌ Error in Lambda:")
        traceback.print_exc()
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
