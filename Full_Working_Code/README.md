# AgenticAI – Smart Prescription Reader and Voice Reminder

## Project Overview
This project combines prescription OCR, AI-based medication extraction, human verification, and voice-based medication reminders.

## Project Structure

- app.py – Flask voice reminder application
- requirements.txt – Python dependencies
- START_AGENTICAI.bat – Startup script
- start_all.ps1 – Startup automation
- Person_B/PrescriptionOCR/basicocr.html – Prescription OCR interface
- Person_B/PrescriptionOCR/prescription_ocr_workflow.json – n8n workflow
- talkbot/main.py – Talkbot source code

## Prescription OCR
1. Upload a prescription image.
2. Extract text using Tesseract.js.
3. Send the extracted text to n8n.
4. Process medication information.
5. Review and confirm the extracted details.
6. Submit confirmed schedules to Flask.

## Voice Reminder Agent
- Receives confirmed medication schedules.
- Stores schedules locally.
- Runs automatic voice reminders.
- Supports speech recognition and text-to-speech.
- Supports caregiver notifications for missed reminders.

## Installation

Python 3.11 is recommended.

Install dependencies:

    pip install -r requirements.txt

## Configuration

Set the caregiver ID locally:

    $env:CAREGIVER_CHAT_ID = "YOUR_CAREGIVER_CHAT_ID"

Configure Ollama, n8n, and required notification credentials separately.

## Run Application

    python app.py

The Flask application uses port 5000 by default.

## n8n Setup

1. Start n8n.
2. Import the prescription OCR workflow JSON.
3. Configure required connections.
4. Activate the workflow.
5. Ensure the HTML webhook URL matches the active n8n webhook.

## Privacy

Real medication schedules and reminder history are stored locally and must not be committed to Git.

Never commit API keys, bot tokens, or personal credentials.
