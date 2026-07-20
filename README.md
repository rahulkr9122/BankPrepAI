# BankPrepAI

BankPrepAI is an AI-powered platform designed to help students prepare for competitive banking exams like SBI Clerk/PO and IBPS Clerk/PO. It uses Large Language Models (LLMs) via the Groq API to generate realistic, exam-style multiple-choice questions on demand, providing a fresh and challenging practice set every time.

## Technical Flow

The application is a monolithic Flask web server that handles both the frontend UI and the backend logic.

1.  **Frontend (HTML/CSS/JavaScript)**: The user interacts with a simple web interface built with HTML, styled with CSS, and powered by vanilla JavaScript.
    *   The user selects an exam type (e.g., "SBI PO") or a specific topic to practice.
    *   An AJAX request is sent from the browser to the Flask backend (`/api/generate-exam` or `/api/generate-topic-exam`).

2.  **Backend (Flask)**:
    *   The Flask server receives the request and identifies the required exam configuration (topics, number of questions, difficulty) from a predefined Python dictionary (`EXAM_LIBRARY`).
    *   It constructs a detailed prompt for the LLM, specifying the exam type, topics, sub-topics, difficulty, and desired JSON output format.
    *   The backend calls the `call_groq` function to send the prompt to the Groq API.

3.  **Groq API Integration**:
    *   The `call_groq` function manages a list of Groq API keys for reliability. It rotates through the available keys in a round-robin fashion.
    *   If an API call fails due to authentication errors, rate limits, or other issues, it automatically switches to the next available key and retries.
    *   If the API returns a JSON validation error, it retries the request with the same key but appends a reminder to the prompt to ensure valid JSON output.
    *   The request to Groq specifies that the response must be a JSON object, which the model generates based on the prompt.

4.  **Question Processing**:
    *   The backend receives the raw JSON string from Groq.
    *   The `extract_and_normalize_questions` function parses the JSON, validates its structure, and normalizes the questions into a consistent format. It also deduplicates questions to ensure variety.
    *   The processed list of questions is stored in the user's server-side session (`flask_session`). Storing questions on the server is crucial because the large amount of data can exceed the browser's 4KB cookie size limit.

5.  **Exam and Scoring**:
    *   The user is redirected to the exam page, where the questions are loaded from the session and displayed.
    *   After the user submits their answers, the frontend sends them to the `/api/score-exam` endpoint.
    *   The backend calculates the score (with negative marking), analyzes performance by topic and sub-topic, and generates personalized suggestions for improvement.
    *   The final report is stored in the session history and displayed on the dashboard.

## Key Features

-   **Dynamic Question Generation**: Leverages the Groq API to create unique banking exam questions based on specified patterns, topics, and difficulty levels.
-   **API Key Load Balancing**: Implements a robust round-robin system to rotate through multiple Groq API keys, ensuring high availability and resilience against single-key failures (e.g., rate limits, authentication issues).
-   **Realistic Exam Simulation**: Mimics the structure of real banking exams with sections for English, Numerical Ability, and Reasoning.
-   **Server-Side Session Management**: Uses `Flask-Session` to store large exam data on the server's filesystem, overcoming browser cookie size limitations.
-   **Detailed Performance Analysis**: Provides a comprehensive dashboard with score, accuracy by topic/sub-topic, and actionable suggestions for improvement.
-   **Containerized & Deployable**: Comes with a `Dockerfile` and `render.yaml` for easy deployment on cloud platforms like Render.

## API Key Management

The application is designed to handle multiple Groq API keys to distribute the load and enhance reliability.

-   **Configuration**: API keys should be stored in a `.env` file in the `backend` directory, using the variable `GROQ_API_KEYS` as a comma-separated string:
    ```
    GROQ_API_KEYS="key_1,key_2,key_3"
    ```
-   **Rotation Logic**: The system maintains an index for the last used key in the user's session. On each new exam generation request, it starts with the next key in the list and cycles through them if failures occur. This ensures that load is distributed across all available keys over time.

## Project Structure

```
.
├── backend/
│   ├── app.py              # Main Flask application file
│   ├── requirements.txt    # Python dependencies
│   ├── .env.example        # Example environment variables
│   ├── templates/          # HTML templates for the UI
│   │   ├── index.html
│   │   ├── exam.html
│   │   ├── topic_wise_exam.html
│   │   └── dashboard.html
│   ├── static/             # CSS stylesheets
│   └── flask_session/      # Directory for server-side session files (auto-generated)
├── Dockerfile              # Container configuration for deployment
└── render.yaml             # Deployment configuration for Render.com
```

## Installation and Running

### Prerequisites

-   Python 3.9+ and `pip`
-   Git

### Local Setup

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd BankPrepAI/backend
    ```

2.  **Create a virtual environment:**
    ```bash
    python -m venv venv
    # On Windows PowerShell:
    .\venv\Scripts\Activate.ps1
    # On macOS/Linux:
    # source venv/bin/activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure environment variables:**
    Create a file named `.env` inside the `backend` directory and add your Groq API keys.
    ```env
    # backend/.env
    GROQ_API_KEYS="your_groq_api_key_1,your_groq_api_key_2"
    SECRET_KEY="a_strong_random_secret_key"
    ```

5.  **Run the application:**
    ```bash
    flask run
    ```
    The application will be available at `http://127.0.0.1:5000`.

## Deployment

This project is configured for easy deployment on **Render**.

1.  Push your code to a GitHub repository.
2.  On the Render dashboard, create a new "Web Service".
3.  Connect your GitHub repository.
4.  Render will automatically detect the settings from `render.yaml`:
    *   **Service Name**: `bankprepai`
    *   **Environment**: Python
    *   **Build Command**: `pip install -r backend/requirements.txt`
    *   **Start Command**: `gunicorn --bind 0.0.0.0:5000 backend.app:app`
5.  In the "Environment" tab, add your `GROQ_API_KEYS` and `SECRET_KEY` as environment variables. Make sure to set them to "sync: false" if you are using a public repository to keep them secure.
6.  Click "Create Web Service" to deploy.
