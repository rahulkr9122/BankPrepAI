import json
import os
import re

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from flask_session import Session
from groq import Groq
import requests
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "bankprepai-secret")

# Configure server-side sessions.
# This stores session data on the server's filesystem instead of in browser cookies,
# which is necessary because the list of exam questions can be larger than
# the browser's cookie size limit (around 4KB). Storing it on the server
# avoids this limitation and prevents the application from crashing.
SESSION_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'flask_session')
os.makedirs(SESSION_DIR, exist_ok=True)
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = SESSION_DIR
app.config["SESSION_PERMANENT"] = False

CORS(app)
Session(app)

# OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
# DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "minimax-m3:cloud")
# OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))
# QUESTION_BATCH_SIZE = int(os.getenv("QUESTION_BATCH_SIZE", "10"))
# USE_OLLAMA = str(os.getenv("USE_OLLAMA", "true")).lower() in {"1", "true", "yes", "on"}
# OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.8"))

# GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-pro")
# USE_GEMINI = str(os.getenv("USE_GEMINI", "true")).lower() in {"1", "true", "yes", "on"}
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
USE_GROQ = str(os.getenv("USE_GROQ", "true")).lower() in {"1", "true", "yes", "on"}
QUESTION_BATCH_SIZE = int(os.getenv("QUESTION_BATCH_SIZE", "10"))

EXAM_LIBRARY = {
    "SBI Clerk": {
        "difficulty": "easy to moderate (clerical-level)",
        "description": "Balanced clerical-level prep for SBI Clerk",
        "sections": [
            {"topic": "English", "questions": 30, "duration": 20},
            {"topic": "Numerical Ability", "questions": 35, "duration": 20},
            {"topic": "Reasoning", "questions": 35, "duration": 20}
        ]
    },
    "SBI PO": {
        "difficulty": "moderate to high (probationary officer-level)",
        "description": "Higher difficulty sectional mix for SBI PO",
        "sections": [
            {"topic": "English", "questions": 30, "duration": 20},
            {"topic": "Numerical Ability", "questions": 35, "duration": 20},
            {"topic": "Reasoning", "questions": 35, "duration": 20}
        ]
    },
    "IBPS Clerk": {
        "difficulty": "easy to moderate (clerical-level)",
        "description": "Balanced clerical-level prep for IBPS Clerk",
        "sections": [
            {"topic": "English", "questions": 30, "duration": 20},
            {"topic": "Numerical Ability", "questions": 35, "duration": 20},
            {"topic": "Reasoning", "questions": 35, "duration": 20}
        ]
    },
    "IBPS PO": {
        "difficulty": "moderate to high (banking officer-level)",
        "description": "Tougher sectional MCQ prep for IBPS PO",
        "sections": [
            {"topic": "English", "questions": 30, "duration": 20},
            {"topic": "Numerical Ability", "questions": 35, "duration": 20},
            {"topic": "Reasoning", "questions": 35, "duration": 20}
        ]
    },
    "RRB Clerk": {
        "difficulty": "easy to moderate (regional-level clerical)",
        "description": "RRB clerk practice with quantitative and reasoning focus",
        "sections": [
            {"topic": "Numerical Ability", "questions": 40, "duration": 25},
            {"topic": "Reasoning", "questions": 40, "duration": 25}
        ]
    },
    "RRB PO": {
        "difficulty": "moderate to high (regional officer-level)",
        "description": "RRB PO mix emphasizing aptitude and reasoning",
        "sections": [
            {"topic": "Numerical Ability", "questions": 40, "duration": 25},
            {"topic": "Reasoning", "questions": 40, "duration": 25}
        ]
    }
}


def extract_and_normalize_questions(json_string):
    """
    Parses a JSON string that is expected to contain questions,
    normalizes the structure, and returns a list of question dicts.
    """
    try:
        parsed = json.loads(json_string)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to decode JSON: {exc}") from exc

    if isinstance(parsed, dict):
        if isinstance(parsed.get("questions"), list):
            question_list = parsed["questions"]
        elif all(key in parsed for key in ("question", "options", "answer")):
            # Handle case where it returns a single question object
            question_list = [parsed]
        else:
            raise ValueError("JSON object does not contain a 'questions' list or is not a single question object.")
    elif isinstance(parsed, list):
        question_list = parsed
    else:
        raise ValueError("Expected a JSON object or array of questions.")

    normalized = []
    for item in question_list:
        if not isinstance(item, dict):
            continue  # Skip malformed items

        options = item.get("options") or []
        answer = item.get("answer")
        # Normalize answer if it's an index
        if answer not in options and isinstance(answer, int):
            if 0 <= answer < len(options):
                answer = options[answer]

        normalized.append({
            "question": item.get("question"),
            "options": options,
            "answer": answer,
            "topic": item.get("topic") or "General Banking",
        })

    return normalized



def call_groq(prompt):
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY is not set.")

    client = Groq(api_key=GROQ_API_KEY, timeout=180.0)
    retries = 3
    for attempt in range(retries):
        try:
            chat_completion = client.chat.completions.create(
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                model=GROQ_MODEL,
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            raw_text = chat_completion.choices[0].message.content
            return extract_and_normalize_questions(raw_text)
        except groq.BadRequestError as e:
            if "json_validate_failed" in str(e):
                app.logger.warning(f"Groq JSON validation failed on attempt {attempt + 1}. Retrying...")
                # Modify the prompt slightly to encourage a different response
                prompt += " "
                continue
            raise RuntimeError(f"Groq API call failed: {e}") from e
        except Exception as exc:
            if "response_format" in str(exc):
                raise RuntimeError(f"The selected model '{GROQ_MODEL}' may not support JSON mode. Error: {exc}") from exc
            raise RuntimeError(f"Groq API call failed: {exc}") from exc
    raise RuntimeError("Groq API call failed after multiple retries.")




def build_prompt(exam_type, topics, difficulty, count, batch_number, total_batches):
    topic_list = ", ".join(topics)
    
    prompt_lines = [
        f"Generate exactly {count} multiple-choice banking mock test questions for the exam type '{exam_type}'. "
        f"This is batch {batch_number} of {total_batches}. "
        f"Required syllabus topics: {topic_list}. "
        f"Difficulty must match '{difficulty}'. "
        "Create a completely fresh, fully new question set every time this request is made. "
        "Do not reuse prior questions, do not repeat the same wording patterns, and do not fall back to any canned bank. "
        "Create a balanced mix of questions distributed across all listed topics. "
    ]

    # Add topic-specific instructions
    if "English" in topics:
        prompt_lines.append(
            "For English questions, prioritize contextual understanding (reading comprehension, sentence rearrangement, cloze tests) over simple vocabulary. "
        )
    if "Numerical Ability" in topics:
        prompt_lines.append(
            "For Numerical Ability questions, focus on data interpretation, simplification, number series, and arithmetic word problems. Questions must require calculation. "
        )
    if "Reasoning" in topics:
        prompt_lines.append(
            "For Reasoning questions, include puzzles, seating arrangements, syllogisms, and logical deductions. "
        )

    prompt_lines.extend([
        "Use realistic bank exam wording and a clear mix of easy, moderate, and higher-value questions. "
        "Return raw JSON only, no markdown, no explanation, no headings. "
        "The 'topic' field must be one of the required syllabus topics. "
        "Every answer must be exactly one of the option strings, not a number index. "
    ])
    
    return "".join(prompt_lines)


def generate_questions_in_batches(exam_type, topics, difficulty, count):
    questions = []
    remaining = count
    batch_index = 1
    total_batches = max(1, (count + QUESTION_BATCH_SIZE - 1) // QUESTION_BATCH_SIZE)

    while remaining > 0:
        batch_size = min(QUESTION_BATCH_SIZE, remaining)
        prompt = build_prompt(exam_type, topics, difficulty, batch_size, batch_index, total_batches)
        
        batch_questions = call_groq(prompt)

        if not batch_questions:
            raise RuntimeError(f"Groq returned no questions for batch {batch_index}/{total_batches}")

        questions.extend(batch_questions)
        remaining -= len(batch_questions)
        batch_index += 1

    return questions[:count]


def get_exam_config(exam_type):
    key = (exam_type or "SBI Clerk").strip()
    if key not in EXAM_LIBRARY:
        key = "SBI Clerk"
    return EXAM_LIBRARY[key]


@app.get("/")
def index():
    return render_template("index.html")





@app.get("/topic-wise-exam")
def topic_wise_exam():
    return render_template("topic_wise_exam.html")


@app.get("/exam")
def exam():
    """Renders the main exam interface page."""
    questions = session.get("exam_questions")
    exam_type = session.get("exam_type")

    if not questions or not exam_type:
        # If there's no exam in the session, redirect to the homepage.
        return redirect(url_for("index"))

    config = get_exam_config(exam_type)
    total_duration = sum(section.get("duration", 20) for section in config.get("sections", []))
    return render_template("exam.html", questions=questions, exam_type=exam_type, total_duration=total_duration)


@app.get("/api/health")
def health():
    groq_status = "down"
    groq_error = None
    model_found = False

    if not GROQ_API_KEY:
        groq_error = "GROQ_API_KEY is not set."
    else:
        try:
            client = Groq(api_key=GROQ_API_KEY, timeout=30.0)
            # A simple chat completion to verify connection and model
            _ = client.chat.completions.create(
                messages=[{"role": "user", "content": "ping"}],
                model=GROQ_MODEL,
            )
            groq_status = "ok"
            model_found = True
            groq_error = "Groq API is running and the model is available."
        except Exception as e:
            if "model not found" in str(e).lower():
                groq_error = f"Model '{GROQ_MODEL}' not found. Please check the GROQ_MODEL name in your .env file or app.py. Valid models include 'llama3-8b-8192' and 'mixtral-8x7b-32768'."
            else:
                groq_error = f"Groq API connection failed: {e}"

    return jsonify({
        "status": "ok",
        "app": "BankPrepAI",
        "groq_details": {
            "status": groq_status,
            "model_found": model_found,
            "message": groq_error
        }
    })


@app.get("/api/exam-types")
def exam_types():
    response_data = []
    for exam_name, config in EXAM_LIBRARY.items():
        sections = config.get("sections", [])
        topics = [section["topic"] for section in sections]
        total_duration = sum(section["duration"] for section in sections)
        
        response_data.append({
            "name": exam_name,
            "topics": topics,
            "difficulty": config["difficulty"],
            "duration": total_duration,
            "description": config["description"],
            "sections": sections
        })

    return jsonify({"examTypes": response_data})


@app.post("/api/generate-exam")
def generate_exam():
    app.logger.info("Received request for /api/generate-exam")
    payload = request.get_json(silent=True) or {}
    exam_type = payload.get("examType")
    app.logger.info(f"Exam type from payload: {exam_type}")
    app.logger.info(f"Using Groq model: '{GROQ_MODEL}'")

    if not exam_type:
        app.logger.warning("examType is missing from payload, returning 400.")
        return jsonify({"error": "examType is a required field."}), 400

    config = get_exam_config(exam_type)
    sections = config.get("sections", [])
    
    if not sections:
        return jsonify({"error": f"No sections found for exam type '{exam_type}'."}), 404

    topics = [section["topic"] for section in sections]
    total_questions = sum(section["questions"] for section in sections)
    difficulty = config.get("difficulty")

    try:
        questions = generate_questions_in_batches(exam_type, topics, difficulty, total_questions)
        # Store questions and the exam type in the session for the exam page to use.
        session["exam_questions"] = questions
        session["exam_type"] = exam_type
        # Respond with a URL to redirect the user to the exam page.
        # The frontend will handle the redirection.
        return jsonify({"message": "Exam generated successfully.", "redirectUrl": url_for("exam")})
    except Exception as e:
        app.logger.error(f"Error generating questions for exam '{exam_type}': {e}", exc_info=True)
        return jsonify({"error": "Failed to generate exam questions. The AI service might be down or misconfigured."}), 500


@app.post("/api/generate-topic-exam")
def generate_topic_exam():
    app.logger.info("Received request for /api/generate-topic-exam")
    payload = request.get_json(silent=True) or {}
    exam_type = payload.get("examType")
    topic = payload.get("topic")

    if not exam_type or not topic:
        app.logger.warning("examType or topic is missing from payload, returning 400.")
        return jsonify({"error": "examType and topic are required fields."}), 400

    config = get_exam_config(exam_type)
    difficulty = config.get("difficulty")
    
    section_config = next((section for section in config.get("sections", []) if section["topic"] == topic), None)

    if section_config:
        count = section_config.get("questions", 10)
        duration = section_config.get("duration", 10)
    else:
        app.logger.warning(f"Topic '{topic}' not found in exam '{exam_type}'. Using default values for count and duration.")
        count = 10
        duration = 10

    try:
        questions = generate_questions_in_batches(exam_type, [topic], difficulty, count)
        session["exam_questions"] = questions
        session["exam_type"] = exam_type
        return jsonify({
            "message": "Topic exam generated successfully.",
            "questions": questions,
            "examType": exam_type,
            "topic": topic,
            "difficulty": difficulty,
            "duration": duration
        })
    except Exception as e:
        app.logger.error(f"Error generating questions for topic '{topic}': {e}", exc_info=True)
        return jsonify({"error": "Failed to generate topic exam questions. The AI service might be down or misconfigured."}), 500


@app.post("/api/score-exam")
def score_exam():
    payload = request.get_json(silent=True) or {}
    # The session should be the single source of truth for the questions.
    # This prevents the client from manipulating the questions and ensures all sections are scored.
    questions = session.get("exam_questions")
    answers = payload.get("answers") or {}

    if not questions:
        return jsonify({"error": "Exam session not found or expired. Please start a new exam."}), 400

    score = 0
    results = []
    for index, question in enumerate(questions, start=1):
        user_answer = answers.get(str(index - 1))
        correct_answer = question.get("answer")
        is_correct = user_answer == correct_answer
        if is_correct:
            score += 1

        results.append({
            "question": question.get("question"),
            "topic": question.get("topic") or "General Banking",
            "userAnswer": user_answer,
            "correctAnswer": correct_answer,
            "isCorrect": is_correct,
            "options": question.get("options", [])
        })

    total = len(questions)
    percentage = round((score / total) * 100, 2) if total else 0
    passed = percentage >= 60

    return jsonify({
        "score": score,
        "total": total,
        "percentage": percentage,
        "passed": passed,
        "results": results
    })


@app.errorhandler(404)
def not_found_error(error):
    """Custom 404 error handler to return JSON for API routes."""
    if request.path.startswith('/api/'):
        return jsonify({
            "error": "Not Found",
            "message": f"The API endpoint '{request.url}' does not exist. Please check the URL."
        }), 404
    return "<h1>404 Not Found</h1><p>The page you are looking for does not exist.</p>", 404


@app.errorhandler(500)
def internal_server_error(error):
    """Custom 500 error handler to return JSON for API routes."""
    app.logger.error(f"Server Error: {error}", exc_info=True)
    if request.path.startswith('/api/'):
        return jsonify({
            "error": "Internal Server Error",
            "message": "An unexpected error occurred on the server. Please check the logs."
        }), 500
    return "<h1>500 Internal Server Error</h1><p>Something went wrong.</p>", 500


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
