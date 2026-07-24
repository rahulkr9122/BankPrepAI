import json
import os
import re
import datetime
import time

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from flask_session import Session
# from groq import Groq
# import groq
# import google.generativeai as genai
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

# # GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# Load multiple Groq API keys for load balancing
# GROQ_API_KEYS_STR = os.getenv("GROQ_API_KEYS", "")
# GROQ_API_KEYS = [key.strip() for key in GROQ_API_KEYS_STR.split(',') if key.strip()]

# if not GROQ_API_KEYS:
#     # Fallback to the single key environment variable for backward compatibility
#     single_key = os.getenv("GROQ_API_KEY")
#     if single_key:
#         GROQ_API_KEYS.append(single_key)

# if not GROQ_API_KEYS:
#     app.logger.warning("No Groq API keys found. Please set `GROQ_API_KEYS` in your .env file as a comma-separated string.")

# GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
# USE_GROQ = str(os.getenv("USE_GROQ", "true")).lower() in {"1", "true", "yes", "on"}

# Gemini API Keys for load balancing
GEMINI_API_KEYS_STR = os.getenv("GEMINI_API_KEYS", "")
GEMINI_API_KEYS = [key.strip() for key in GEMINI_API_KEYS_STR.split(',') if key.strip()]

if not GEMINI_API_KEYS:
    # Fallback to the single key environment variable for backward compatibility
    single_key = os.getenv("GEMINI_API_KEY")
    if single_key:
        GEMINI_API_KEYS.append(single_key)

if not GEMINI_API_KEYS:
    app.logger.warning("No Gemini API keys found. Please set `GEMINI_API_KEYS` or `GEMINI_API_KEY` in your .env file.")

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
USE_GEMINI = True  # Default to using Gemini


EXAM_LIBRARY = {
    "SBI Clerk": {
        "difficulty": "easy to moderate (clerical-level)",
        "description": "Balanced clerical-level prep for SBI Clerk",
        "prompt_guidance": "For the Reasoning section, provide 'moderate to hard' questions with complex puzzles. For all other sections, maintain the 'easy to moderate (clerical-level)' difficulty.",
        "sections": [
            {"topic": "English", "questions": 30, "duration": 20},
            {"topic": "Numerical Ability", "questions": 35, "duration": 20},
            {"topic": "Reasoning", "questions": 35, "duration": 20}
        ]
    },
    "SBI PO": {
        "difficulty": "moderate to high (probationary officer-level)",
        "description": "Higher difficulty sectional mix for SBI PO",
        "prompt_guidance": "Generate challenging questions appropriate for an officer-level exam. Reasoning puzzles should be complex and require deep logical thinking. Numerical ability questions should involve multiple concepts and tricky calculations. English questions should test subtle grammar nuances.",
        "sections": [
            {"topic": "English", "questions": 30, "duration": 20},
            {"topic": "Numerical Ability", "questions": 35, "duration": 20},
            {"topic": "Reasoning", "questions": 35, "duration": 20}
        ]
    },
    "IBPS Clerk": {
        "difficulty": "easy to moderate (clerical-level)",
        "description": "Balanced clerical-level prep for IBPS Clerk",
        "prompt_guidance": "Similar to SBI Clerk. Questions should be direct and test fundamental concepts. Ensure reasoning questions are logically sound but not overly convoluted. Numerical questions should be speed-based.",
        "sections": [
            {"topic": "English", "questions": 30, "duration": 20},
            {"topic": "Numerical Ability", "questions": 35, "duration": 20},
            {"topic": "Reasoning", "questions": 35, "duration": 20}
        ]
    },
    "IBPS PO": {
        "difficulty": "moderate to high (banking officer-level)",
        "description": "Tougher sectional MCQ prep for IBPS PO",
        "prompt_guidance": "Focus on application-based questions. Reasoning should include modern puzzle types. Numerical ability should feature complex data interpretation sets. English should test advanced vocabulary and comprehension skills.",
        "sections": [
            {"topic": "English", "questions": 30, "duration": 20},
            {"topic": "Numerical Ability", "questions": 35, "duration": 20},
            {"topic": "Reasoning", "questions": 35, "duration": 20}
        ]
    },
    "RRB Clerk": {
        "difficulty": "easy to moderate (regional-level clerical)",
        "description": "RRB clerk practice with quantitative and reasoning focus",
        "prompt_guidance": "Generate questions with a rural and cooperative bank flavor where possible. Focus on speed and accuracy. Reasoning and Numerical Ability are the only sections, so ensure a good spread of sub-topics within them.",
        "sections": [
            {"topic": "Numerical Ability", "questions": 40, "duration": 25},
            {"topic": "Reasoning", "questions": 40, "duration": 25}
        ]
    },
    "RRB PO": {
        "difficulty": "moderate to high (regional officer-level)",
        "description": "RRB PO mix emphasizing aptitude and reasoning",
        "prompt_guidance": "Slightly less difficult than IBPS/SBI PO, but still challenging. Include data interpretation and puzzles relevant to rural banking scenarios if possible. The focus is on problem-solving skills for a regional context.",
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
        # Gemini may return markdown ```json ... ```, so we extract it.
        if "```json" in json_string:
            json_string = json_string[json_string.find("```json") + 7:json_string.rfind("```")]
        parsed = json.loads(json_string)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to decode JSON: {exc}. Original string was: {json_string}") from exc

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
            "sub_topic": item.get("sub_topic") or "General",
        })

    return normalized


def call_gemini(prompt):
    if not GEMINI_API_KEYS:
        raise ValueError("GEMINI_API_KEYS are not set. Please add them to your .env file.")

    start_key_index = session.get("gemini_key_index", 0)
    
    for i in range(len(GEMINI_API_KEYS)):
        key_index = (start_key_index + i) % len(GEMINI_API_KEYS)
        current_key = GEMINI_API_KEYS[key_index]
        
        app.logger.info(f"Using Gemini API key with index: {key_index}")
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={current_key}"
        
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "candidateCount": 1,
                "response_mime_type": "application/json",
            }
        }

        for attempt in range(3):
            try:
                response = requests.post(url, json=payload, timeout=180)
                response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)

                content_type = response.headers.get('Content-Type', '')
                if 'application/json' not in content_type:
                    app.logger.error(f"Gemini API returned non-JSON response for key index {key_index}. "
                                     f"Content-Type: {content_type}. Response body: {response.text[:500]}")
                    break # Switch key, as this might be a block page or captcha

                raw_text = response.json()['candidates'][0]['content']['parts'][0]['text']
                session["gemini_key_index"] = key_index
                return extract_and_normalize_questions(raw_text)

            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429: # Rate limit error
                    app.logger.warning(f"Gemini API key at index {key_index} is rate-limited. Switching to the next key.")
                    break # Switch key
                elif e.response.status_code in [400, 403]: # Bad request or permission error, likely bad key
                    app.logger.warning(f"Gemini API key at index {key_index} failed with status {e.response.status_code}. Switching key. Error: {e.response.text}")
                    break # Switch key
                else:
                    app.logger.error(f"An HTTP error occurred with key at index {key_index}: {e}. Retrying...")
                    time.sleep(1) # a short delay before retrying
                    continue # Retry with same key
            except ValueError as e:
                if "Failed to decode JSON" in str(e):
                    app.logger.warning(f"Gemini JSON validation failed on attempt {attempt + 1} with key index {key_index}. Retrying prompt. Error: {e}")
                    prompt += "\nReminder: The output must be a single, valid JSON object and nothing else. Do not include any text outside of the JSON structure."
                    time.sleep(1)
                    continue # Retry with same key, modified prompt
                else:
                    app.logger.error(f"A ValueError occurred with key at index {key_index}: {e}. Switching key.")
                    break # Other ValueError, switch key
            except Exception as exc:
                app.logger.error(f"An unexpected error occurred with key at index {key_index}: {exc}. Switching key.")
                break  # Switch key
    
    raise RuntimeError("Gemini API call failed for all available keys and retries.")


def build_prompt(exam_type, topics, difficulty, count, guidance):
    topic_list = ", ".join(topics)
    
    prompt_lines = [
        f"""You are an expert creator of mock test questions for Indian banking exams. Your task is to generate a high-quality, realistic question paper. 
Generate exactly {count} multiple-choice questions for the '{exam_type}' exam. 
The questions must cover these topics: {topic_list}. 
The overall difficulty must be strictly '{difficulty}'. 
The style, format, and complexity of the questions should closely mirror the last 2-3 years of official papers for this specific exam. 
Crucially, create a completely fresh and new question set. Do not repeat questions or patterns from your training data. Every single question in this response must be unique. 
Distribute the questions evenly across the requested topics. """
    ]

    # Add the new, specific guidance for the exam type
    if guidance:
        prompt_lines.append(f"Follow this specific guidance for '{exam_type}': {guidance}. ")

    # Add topic-specific instructions
    if "English" in topics:
        prompt_lines.append(
            "For English, include a mix of: reading comprehension, phrase replacement, fill in the blanks, odd sentence out, para jumbles, cloze test, sentence connectors, misspelt words, error detection, word swap, word rearrangement, idioms/phrases, and synonyms/antonyms. "
        )
    if "Numerical Ability" in topics:
        prompt_lines.append(
            "For Numerical Ability, include: simplification/approximation, number series (missing/wrong), quadratic equations, Data Interpretation (DI), and Arithmetic (e.g., time/work, pipes/cisterns, age problems, average, ratio, interest, partnership). All questions must require calculation and logical steps, not just be simple knowledge questions. "
        )
    if "Reasoning" in topics:
        prompt_lines.append(
            "For Reasoning, it is CRITICAL that all questions are logically sound, unambiguous, and have one single correct answer among the options. Double-check your logic. Include a mix of: blood relation, direction/distance, alphanumeric series, syllogism, coding-decoding, seating arrangement, inequality, and puzzles (box, floor, day/month/year, linear row). Ensure puzzles are solvable within a reasonable time for an exam setting. "
        )

    prompt_lines.append(
        """Return raw JSON only. Do not include markdown, explanations, or any text outside of the JSON structure. 
The JSON must be a single object with a 'questions' key, which is a list of question objects. 
Each question object must have this exact structure: {"question": "...", "options": ["..."], "answer": "...", "topic": "...", "sub_topic": "..."}. 
The 'topic' must be one of the required syllabus topics. 
The 'sub_topic' must be the specific area (e.g., 'reading comprehension', 'seating arrangement', 'data interpretation'). 
The 'answer' must be the full text of one of the provided options, not a letter or index. 
Verify that every question is factually correct and that the provided answer is unambiguously the right one. """
    )
    
    return "".join(prompt_lines)


def generate_questions(exam_type, topics, difficulty, count):
    """Generates the specified number of questions in a single API call, ensuring no duplicates."""
    config = get_exam_config(exam_type)
    guidance = config.get("prompt_guidance", "")

    prompt = build_prompt(exam_type, topics, difficulty, count, guidance)
    
    questions = call_gemini(prompt)

    if not questions:
        raise RuntimeError("API returned no questions.")

    unique_questions = []
    seen_questions = set()
    for q in questions:
        question_text = q.get("question", "").strip().lower()
        if question_text and question_text not in seen_questions:
            unique_questions.append(q)
            seen_questions.add(question_text)
    
    questions = unique_questions

    if len(questions) < count:
        app.logger.warning(f"AI returned fewer questions ({len(questions)}) than requested ({count}) after deduplication.")
    
    return questions[:count]


def get_exam_config(exam_type):
    key = (exam_type or "SBI Clerk").strip()
    if key not in EXAM_LIBRARY:
        key = "SBI Clerk"
    return EXAM_LIBRARY[key]


@app.get("/")
def index():
    has_history = "exam_history" in session and session["exam_history"]
    return render_template("index.html", has_history=has_history)


@app.get("/dashboard")
def dashboard():
    exam_history = session.get("exam_history", [])
    return render_template("dashboard.html", exam_history=exam_history)


@app.get("/topic-wise-exam")
def topic_wise_exam():
    return render_template("topic_wise_exam.html")


@app.get("/exam")
def exam():
    """Renders the main exam interface page."""
    questions = session.get("exam_questions")
    exam_type = session.get("exam_type")

    if not questions or not exam_type:
        return redirect(url_for("index"))

    config = get_exam_config(exam_type)
    total_duration = sum(section.get("duration", 20) for section in config.get("sections", []))
    return render_template("exam.html", questions=questions, exam_type=exam_type, total_duration=total_duration)


@app.get("/api/health")
def health():
    gemini_status = "down"
    gemini_error = None
    model_found = False
    if not GEMINI_API_KEYS:
        gemini_error = "GEMINI_API_KEYS is not set in the environment."
    else:
        try:
            # Use the first key for the health check
            current_key = GEMINI_API_KEYS[0]
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={current_key}"
            payload = {"contents": [{"parts": [{"text": "ping"}]}]}
            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()
            
            gemini_status = "ok"
            model_found = True
            gemini_error = "Gemini API is running and the model is available."
        except requests.exceptions.HTTPError as e:
             if "model not found" in e.response.text.lower():
                gemini_error = f"Model '{GEMINI_MODEL}' not found. Please check the GEMINI_MODEL name in your .env file or app.py."
             else:
                gemini_error = f"Gemini API connection failed: {e}"
        except Exception as e:
            gemini_error = f"Gemini API connection failed: {e}"

    return jsonify({
        "status": "ok",
        "app": "BankPrepAI",
        "gemini_details": {
            "status": gemini_status,
            "model_found": model_found,
            "message": gemini_error
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
    app.logger.info(f"Using Gemini model: '{GEMINI_MODEL}'")

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
        questions = generate_questions(exam_type, topics, difficulty, total_questions)
        session["exam_questions"] = questions
        session["exam_type"] = exam_type
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
        questions = generate_questions(exam_type, [topic], difficulty, count)
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
    questions = session.get("exam_questions") or []
    answers = payload.get("answers") or {}

    if not questions:
        return jsonify({
            "score": 0.0,
            "totalQuestions": 0,
            "maxScore": 0.0,
            "results": [],
            "performanceByTopic": {},
            "suggestions": ["No exam questions were found in the session. Please start a new exam."]
        })

    score = 0.0
    results = []
    performance_by_topic = {}

    for index, question in enumerate(questions, start=1):
        user_answer = answers.get(str(index - 1))
        correct_answer = question.get("answer")
        topic = question.get("topic") or "General Banking"
        sub_topic = question.get("sub_topic") or "General"

        is_correct = None
        if user_answer:
            is_correct = user_answer == correct_answer

        if topic not in performance_by_topic:
            performance_by_topic[topic] = {}
        if sub_topic not in performance_by_topic[topic]:
            performance_by_topic[topic][sub_topic] = {"correct": 0, "wrong": 0, "unanswered": 0, "total": 0}

        performance_by_topic[topic][sub_topic]["total"] += 1

        if not user_answer:
            performance_by_topic[topic][sub_topic]["unanswered"] += 1
        elif is_correct:
            score += 1
            performance_by_topic[topic][sub_topic]["correct"] += 1
        else:
            score -= 0.5
            performance_by_topic[topic][sub_topic]["wrong"] += 1

        results.append({
            "question": question.get("question"),
            "topic": topic,
            "sub_topic": sub_topic,
            "userAnswer": user_answer,
            "correctAnswer": correct_answer,
            "isCorrect": is_correct,
            "options": question.get("options", [])
        })

    suggestions = []
    for topic, sub_topics in performance_by_topic.items():
        for sub_topic_name, performance in sub_topics.items():
            attempted = performance["correct"] + performance["wrong"]
            if attempted > 0:
                accuracy = (performance["correct"] / attempted) * 100
                if accuracy < 70:
                    suggestions.append(
                        f"Your accuracy in '{sub_topic_name}' ({topic}) is low ({accuracy:.1f}%). Focus on this area."
                    )
            elif performance["unanswered"] > performance["total"] / 2 and performance['total'] > 2:
                suggestions.append(
                    f"You skipped many questions in '{sub_topic_name}' ({topic}). Try to build confidence here."
                )

    final_score = max(0.0, score)

    exam_result = {
        "score": final_score,
        "totalQuestions": len(questions),
        "maxScore": float(len(questions)),
        "results": results,
        "performanceByTopic": performance_by_topic,
        "suggestions": suggestions,
        "examType": session.get("exam_type", "Unknown"),
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    exam_history = session.get("exam_history", [])
    exam_history.append(exam_result)
    session["exam_history"] = exam_history

    session.pop("exam_questions", None)
    session.pop("exam_type", None)

    return jsonify(exam_result)


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
