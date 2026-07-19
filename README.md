# BankPrepAI

BankPrepAI is an AI-powered platform for students to practice for banking exams like SBI and IBPS.

## Project Structure

- `backend/`: Contains the Flask application with the HTML UI and Ollama-powered question generation.

## Getting Started

### Prerequisites

- Python and pip
- Ollama installed locally and running on `http://localhost:11434`

### Installation

```bash
cd backend
python -m venv venv
# On Windows PowerShell:
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

### Run

Open:
- http://127.0.0.1:5000

### Features

- Flask-only UI and backend in one app
- Local Ollama integration for question generation
- Multiple-choice banking exam practice experience
