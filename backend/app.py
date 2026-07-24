import json
import os
import random
import re
import datetime
import time

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from flask_session import Session
import requests
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "bankprepai-secret")

SESSION_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'flask_session')
os.makedirs(SESSION_DIR, exist_ok=True)
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = SESSION_DIR
app.config["SESSION_PERMANENT"] = False

CORS(app)
Session(app)

class NonJsonResponseError(Exception):
    def __init__(self, message, content):
        super().__init__(message)
        self.content = content

# Gemini API Key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    app.logger.warning("No Gemini API key found. Please set `GEMINI_API_KEY` in your .env file.")

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
USE_GEMINI = True

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
    try:
        if "```json" in json_string:
            json_string = json_string[json_string.find("```json") + 7:json_string.rfind("```")]
        parsed = json.loads(json_string)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to decode JSON: {exc}. Original string was: {json_string}") from exc

    if isinstance(parsed, dict):
        if isinstance(parsed.get("questions"), list):
            question_list = parsed["questions"]
        elif all(key in parsed for key in ("question", "options", "answer")):
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
            continue

        options = item.get("options") or []
        answer = item.get("answer")
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
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set. Please add it to your .env file.")

    app.logger.info("Calling Gemini API...")
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "candidateCount": 1,
            "response_mime_type": "application/json",
        }
    }

    try:
        response = requests.post(url, json=payload, timeout=60)
        response.raise_for_status()

        content_type = response.headers.get('Content-Type', '')
        if 'application/json' not in content_type:
            raise NonJsonResponseError(
                f"Gemini API returned non-JSON response. Content-Type: {content_type}",
                response.text
            )

        json_response = response.json()
        
        if 'error' in json_response:
            error_message = json_response['error'].get('message', 'Unknown error')
            app.logger.error(f"Gemini API returned an error: {error_message}")
            raise RuntimeError(f"Gemini API error: {error_message}")

        try:
            raw_text = json_response['candidates'][0]['content']['parts'][0]['text']
            return extract_and_normalize_questions(raw_text)
        except (KeyError, IndexError, TypeError) as e:
            app.logger.error(f"Failed to parse Gemini response structure. Error: {e}. Response: {json_response}")
            raise RuntimeError("Failed to parse Gemini response.")

    except requests.exceptions.Timeout:
        app.logger.error("Request to Gemini API timed out.")
        raise RuntimeError("Request to Gemini API timed out.")
    except requests.exceptions.HTTPError as e:
        app.logger.error(f"An HTTP error occurred: {e}. Status code: {e.response.status_code}. Response: {e.response.text}")
        raise RuntimeError(f"HTTP error from Gemini API: {e.response.status_code}")
    except Exception as exc:
        app.logger.error(f"An unexpected error occurred: {exc}.")
        raise RuntimeError(f"An unexpected error occurred: {exc}")


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

    if guidance:
        prompt_lines.append(f"Follow this specific guidance for '{exam_type}': {guidance}. ")

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
    config = get_exam_config(exam_type)
    guidance = config.get("prompt_guidance", "")

    # Over-request to account for deduplication
    buffer_factor = 1.2
    target_count = int(count * buffer_factor)

    all_questions = []
    batch_size = 12
    remaining_questions = target_count

    while remaining_questions > 0:
        current_batch_size = min(batch_size, remaining_questions)
        app.logger.info(f"Generating a batch of {current_batch_size} questions...")

        prompt = build_prompt(exam_type, topics, difficulty, current_batch_size, guidance)

        try:
            questions_batch = call_gemini(prompt)
            if questions_batch:
                all_questions.extend(questions_batch)
            else:
                app.logger.warning("API returned no questions for a batch.")

        except Exception as e:
            app.logger.error(f"Failed to generate a batch of questions: {e}")
            # Continue to the next batch, or you might fail the entire process
            pass

        remaining_questions -= current_batch_size

        if remaining_questions > 0:
            app.logger.info("Waiting for 2 seconds before next API call...")
            time.sleep(2)

    if not all_questions:
        raise RuntimeError("API returned no questions for any batch.")

    unique_questions = []
    seen_questions = set()
    for q in all_questions:
        question_text = q.get("question", "").strip().lower()
        if question_text and question_text not in seen_questions:
            unique_questions.append(q)
            seen_questions.add(question_text)

    questions = unique_questions
    if len(questions) < count:
        app.logger.warning(
            f"AI returned {len(questions)} unique questions, which is less than the requested {count}, even after attempting to generate {target_count}."
        )

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
    questions = session.get("exam_questions")
    exam_type = session.get("exam_type")
    if not questions or not exam_type:
        return redirect(url_for("index"))

    # Shuffle the questions for randomness
    random.shuffle(questions)
    
    config = get_exam_config(exam_type)
    total_duration = sum(section.get("duration", 20) for section in config.get("sections", []))
    return render_template("exam.html", questions=questions, exam_type=exam_type, total_duration=total_duration)


@app.get("/api/health")
def health():
    gemini_status = "down"
    gemini_error = None
    model_found = False
    if not GEMINI_API_KEY:
        gemini_error = "GEMINI_API_KEY is not set in the environment."
    else:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
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
    except NonJsonResponseError as e:
        app.logger.error(f"Caught a non-JSON response from the API: {e.content[:500]}")
        error_message = f"The API returned an unexpected HTML page, indicating a server or network error. Raw HTML: {e.content}"
        return jsonify({"error": error_message}), 500
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
    except NonJsonResponseError as e:
        app.logger.error(f"Caught a non-JSON response from the API for topic '{topic}': {e.content[:500]}")
        error_message = f"The API returned an unexpected HTML page, indicating a server or network error. Raw HTML: {e.content}"
        return jsonify({"error": error_message}), 500
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
    if request.path.startswith('/api/'):
        return jsonify({
            "error": "Not Found",
            "message": f"The API endpoint '{request.url}' does not exist. Please check the URL."
        }), 404
    return "<h1>404 Not Found</h1><p>The page you are looking for does not exist.</p>", 404


@app.errorhandler(500)
def internal_server_error(error):
    app.logger.error(f"Server Error: {error}", exc_info=True)
    if request.path.startswith('/api/'):
        return jsonify({
            "error": "Internal Server Error",
            "message": "An unexpected error occurred on the server. Please check the logs."
        }), 500
    return "<h1>500 Internal Server Error</h1><p>Something went wrong.</p>", 500


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
