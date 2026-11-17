
import csv
import json
import os
import threading
import time
import uuid
from datetime import datetime
from datetime import timedelta

import pyttsx3
import requests
import speech_recognition as sr
from flask import Flask, request, jsonify
from flask_cors import CORS


# ==================================================
# FLASK CONFIGURATION
# ==================================================

app = Flask(__name__)
CORS(app)


# ==================================================
# CONFIGURATION
# ==================================================

REPEAT_INTERVAL_SECONDS = 10
REPEAT_INTERVAL_MINUTES = REPEAT_INTERVAL_SECONDS / 60

MAX_REMINDER_ATTEMPTS = 3
URGENT_AFTER_MISSED_CYCLES = 1

SCHEDULER_CHECK_INTERVAL = 5

SCHEDULE_FILE = "medication_schedules.json"
HISTORY_FILE = "reminder_history.csv"

N8N_MISSED_WEBHOOK_URL = (
    "http://localhost:5678/webhook/medication-missed"
)

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_MODEL = "qwen2.5-coder:7b"
USER_ID = "USER001"
USER_NAME = "User"

CAREGIVER_CHAT_ID = os.getenv("CAREGIVER_CHAT_ID", "")

MEDICATION_NAME = "Inhaler"


# ==================================================
# GLOBAL VARIABLES
# ==================================================

medication_schedules = []

active_reminders = {}

consecutive_missed_cycles = {}

scheduled_reminder_runs = set()

schedule_lock = threading.RLock()

reminder_lock = threading.Lock()


# ==================================================
# MEAL INSTRUCTIONS
# ==================================================

MEAL_INSTRUCTIONS = {
    "before_meal": "Please take this medicine before your meal.",
    "after_meal": "Please take this medicine after your meal."
}

MEAL_LABELS = {
    "before_meal": "Before Meal",
    "after_meal": "After Meal"
}


# ==================================================
# REMINDER MESSAGE
# ==================================================

def get_reminder_message(schedule):

    hour = datetime.now().hour

    if hour < 12:
        greeting = "Good morning"
    elif hour < 17:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"

    meal_timing = schedule.get(
        "before_or_after_food",
        ""
    )

    meal_message = MEAL_INSTRUCTIONS.get(
        meal_timing,
        "Please follow your doctor's meal instructions."
    )

    scheduled_time = schedule.get(
        "current_reminder_time",
        "Not specified"
    )

    return (
        f"{greeting}, {USER_NAME}! "
        f"It is time to take {schedule['medication_name']}. "
        f"Dosage: {schedule['dosage']}. "
        f"Scheduled time: {scheduled_time}. "
        f"{meal_message} "
        "Please confirm once you have taken your medicine."
    )


# ==================================================
# LOAD MEDICATION SCHEDULES
# ==================================================

def load_medication_schedules():

    global medication_schedules

    if not os.path.exists(SCHEDULE_FILE):
        medication_schedules = []
        return

    try:

        with open(
            SCHEDULE_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            medication_schedules = json.load(file)

        if not isinstance(medication_schedules, list):
            raise ValueError("Invalid schedule file format.")

        print(
            f"Loaded {len(medication_schedules)} medication schedules."
        )

    except Exception as error:

        print("Schedule loading error:", error)

        medication_schedules = []


# ==================================================
# SAVE MEDICATION SCHEDULES
# ==================================================

def save_medication_schedules():

    temporary_file = SCHEDULE_FILE + ".tmp"

    with schedule_lock:

        with open(
            temporary_file,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                medication_schedules,
                file,
                indent=4
            )

        os.replace(
            temporary_file,
            SCHEDULE_FILE
        )


# ==================================================
# VALIDATE MEDICATION SCHEDULE
# ==================================================


def validate_medication_schedule(data):

    required_fields = [
        "medication_name",
        "dosage",
        "frequency",
        "reminder_times",
        "start_date",
        "end_date",
        "confirmed"
    ]

    for field in required_fields:
        if field not in data:
            return False, f"Missing required field: {field}"

    for field in ["medication_name", "dosage", "frequency"]:
        if not isinstance(data[field], str) or not data[field].strip():
            return False, f"Invalid or empty field: {field}"

    times = data["reminder_times"]

    if not isinstance(times, list) or not times:
        return False, "At least one exact reminder time is required."

    for reminder_time in times:
        if not isinstance(reminder_time, str):
            return False, "Reminder times must be strings."

        try:
            datetime.strptime(reminder_time, "%H:%M")
        except ValueError:
            return False, f"Invalid reminder time: {reminder_time}. Use HH:MM."

    try:
        start_date = datetime.strptime(
            data["start_date"], "%Y-%m-%d"
        ).date()

        end_date = datetime.strptime(
            data["end_date"], "%Y-%m-%d"
        ).date()

        if end_date < start_date:
            return False, "End date cannot be before start date."

    except (ValueError, TypeError):
        return False, "Dates must use YYYY-MM-DD format."

    if data["confirmed"] is not True:
        return False, "User confirmation is required."

    meal_timing = data.get(
        "before_or_after_food",
        "not_specified"
    )

    allowed_meal_timings = {
        "before_meal",
        "after_meal",
        "with_meal",
        "anytime",
        "not_specified",
        "Not specified"
    }

    if meal_timing not in allowed_meal_timings:
        return False, "Invalid meal instruction."

    return True, "Schedule validation successful."


# ==================================================
# MEDICATION COURSE VALIDATION
# ==================================================

def is_medication_course_active(schedule):

    today = datetime.now().date()

    start_date = datetime.strptime(
        schedule["start_date"],
        "%Y-%m-%d"
    ).date()

    end_date = datetime.strptime(
        schedule["end_date"],
        "%Y-%m-%d"
    ).date()

    return start_date <= today <= end_date


# ==================================================
# N8N / TELEGRAM NOTIFICATION
# ==================================================

def send_n8n_notification(
    slot,
    alert_type,
    missed_count,
    schedule=None,
    scheduled_time=None
):

    medication = (
        schedule.get("medication_name", MEDICATION_NAME)
        if schedule else MEDICATION_NAME
    )

    dosage = (
        schedule.get("dosage", "Not specified")
        if schedule else "Not specified"
    )

    meal_timing = (
        schedule.get("before_or_after_food", "")
        if schedule else ""
    )

    meal_instruction = MEAL_LABELS.get(
        meal_timing,
        "Not specified"
    )

    payload = {

        "user_id": USER_ID,

        "medication": medication,

        "dosage": dosage,

        "slot": slot,

        "scheduled_time": (
            scheduled_time
            or "Not specified"
        ),

        "before_or_after_food": meal_timing,

        "meal_instruction": meal_instruction,

        "status": "missed",

        "alert_type": alert_type,

        "missed_count": missed_count,

        "caregiver_telegram_id": CAREGIVER_CHAT_ID,

        "timestamp": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    }

    try:

        response = requests.post(
            N8N_MISSED_WEBHOOK_URL,
            json=payload,
            timeout=10
        )

        response.raise_for_status()

        print(
            f"{alert_type} notification sent to n8n."
        )

        return True

    except requests.exceptions.RequestException as error:

        print(
            "Notification error:",
            error
        )

        return False


# ==================================================
# TEXT TO SPEECH
# ==================================================

def speak(message):

    try:

        engine = pyttsx3.init()

        engine.setProperty("rate", 160)

        engine.setProperty("volume", 1.0)

        engine.say(message)

        engine.runAndWait()

        engine.stop()

    except Exception as error:

        print("TTS error:", error)


# ==================================================
# SPEECH RECOGNITION
# ==================================================

def listen_for_response(
    timeout=8,
    phrase_time_limit=8
):

    recognizer = sr.Recognizer()

    try:

        with sr.Microphone() as source:

            print("Listening for response...")

            recognizer.adjust_for_ambient_noise(
                source,
                duration=0.5
            )

            audio = recognizer.listen(
                source,
                timeout=timeout,
                phrase_time_limit=phrase_time_limit
            )

        response = recognizer.recognize_google(
            audio,
            language="en-IN"
        )

        print("Recognized:", response)

        return response.lower().strip()

    except sr.WaitTimeoutError:

        return ""

    except sr.UnknownValueError:

        return ""

    except sr.RequestError as error:

        print("Speech recognition error:", error)

        return ""

    except Exception as error:

        print("Microphone error:", error)

        return ""


# ==================================================
# CONFIRMATION DETECTION
# ==================================================

def is_confirmed(response):

    confirmation_phrases = [
        "yes",
        "taken",
        "i took it",
        "done",
        "finished",
        "completed",
        "i have taken",
        "medicine taken",
        "medication taken",
        "yes i have taken it"
    ]

    return any(
        phrase in response
        for phrase in confirmation_phrases
    )


# ==================================================
# REMINDER HISTORY
# ==================================================

def log_reminder(
    slot,
    status,
    response=""
):

    file_exists = os.path.exists(HISTORY_FILE)

    try:

        with open(
            HISTORY_FILE,
            "a",
            newline="",
            encoding="utf-8"
        ) as file:

            writer = csv.writer(file)

            if not file_exists:

                writer.writerow([
                    "timestamp",
                    "slot",
                    "status",
                    "response"
                ])

            writer.writerow([

                datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),

                slot,

                status,

                response
            ])

    except Exception as error:

        print("History logging error:", error)


# ==================================================
# REMINDER LOOP
# ==================================================

def reminder_loop(
    slot,
    session_id,
    schedule,
    scheduled_time
):

    print(
        f"Reminder started for {slot} at {scheduled_time}"
    )

    schedule = dict(schedule)

    schedule["current_reminder_time"] = scheduled_time

    missed_cycles_this_session = 0

    try:

        while True:

            if not is_medication_course_active(schedule):

                speak(
                    f"{USER_NAME}, your medication course "
                    "has reached its end date. "
                    "Reminders have been stopped."
                )

                log_reminder(
                    slot,
                    "COURSE_COMPLETED"
                )

                return

            confirmed = False

            for attempt in range(
                1,
                MAX_REMINDER_ATTEMPTS + 1
            ):

                print(
                    f"Reminder attempt {attempt}/"
                    f"{MAX_REMINDER_ATTEMPTS}"
                )

                speak(
                    get_reminder_message(schedule)
                )

                response = listen_for_response()

                if is_confirmed(response):

                    speak(
                        f"Well done, {USER_NAME}! "
                        f"Your {schedule['medication_name']} "
                        "has been marked as taken."
                    )

                    log_reminder(
                        slot,
                        "CONFIRMED",
                        response
                    )

                    with reminder_lock:

                        consecutive_missed_cycles[slot] = 0

                    confirmed = True

                    break

                if response:

                    log_reminder(
                        slot,
                        "UNCLEAR",
                        response
                    )

                else:

                    log_reminder(
                        slot,
                        "NO_RESPONSE"
                    )

                if attempt < MAX_REMINDER_ATTEMPTS:

                    time.sleep(
                        REPEAT_INTERVAL_SECONDS
                    )

            if confirmed:

                return

            missed_cycles_this_session += 1

            with reminder_lock:

                consecutive_missed_cycles[slot] = (
                    consecutive_missed_cycles.get(slot, 0) + 1
                )

                missed_count = consecutive_missed_cycles[slot]

            log_reminder(
                slot,
                "MISSED_CYCLE",
                str(missed_count)
            )

            send_n8n_notification(
                slot=slot,
                alert_type="MISSED",
                missed_count=missed_count,
                schedule=schedule,
                scheduled_time=scheduled_time
            )

            log_reminder(
                slot,
                "MISSED_EVENT_SENT_TO_N8N"
            )

            if (
                missed_cycles_this_session
                >= URGENT_AFTER_MISSED_CYCLES
            ):

                urgent_sent = send_n8n_notification(
                    slot=slot,
                    alert_type="URGENT",
                    missed_count=missed_count,
                    schedule=schedule,
                    scheduled_time=scheduled_time
                )

                if urgent_sent:

                    log_reminder(
                        slot,
                        "URGENT_EVENT_SENT_TO_N8N"
                    )

                return

    except Exception as error:

        print("Reminder loop error:", error)

        log_reminder(
            slot,
            "ERROR",
            str(error)
        )

    finally:

        with reminder_lock:

            if active_reminders.get(slot) == session_id:

                del active_reminders[slot]

        print(
            f"Reminder stopped for {slot}"
        )


# ==================================================
# AUTOMATIC MEDICATION SCHEDULER
# ==================================================

def medication_scheduler():

    print("Automatic medication scheduler started.")

    while True:

        try:

            now = datetime.now()

            current_time = now.strftime("%H:%M")

            today = now.date().isoformat()

            with schedule_lock:

                schedules = list(medication_schedules)

            for schedule in schedules:

                if not schedule.get("confirmed"):
                    continue

                if not schedule.get("active"):
                    continue

                if not is_medication_course_active(schedule):
                    continue

                if current_time not in schedule.get(
                    "reminder_times",
                    []
                ):
                    continue

                schedule_id = schedule.get("schedule_id")

                run_id = (
                    f"{schedule_id}_{today}_{current_time}"
                )

                if run_id in scheduled_reminder_runs:
                    continue

                slot = f"medication_{schedule_id}"

                with reminder_lock:

                    if slot in active_reminders:
                        continue

                    session_id = str(uuid.uuid4())

                    active_reminders[slot] = session_id

                scheduled_reminder_runs.add(run_id)

                threading.Thread(
                    target=reminder_loop,
                    args=(
                        slot,
                        session_id,
                        schedule,
                        current_time
                    ),
                    daemon=True
                ).start()

        except Exception as error:

            print("Scheduler error:", error)

        time.sleep(
            SCHEDULER_CHECK_INTERVAL
        )


# ==================================================
# RECEIVE MEDICATION SCHEDULE
# ==================================================

@app.route(
    "/api/medications",
    methods=["POST"]
)
def receive_medication_schedule():

    data = request.get_json(silent=True)

    if not isinstance(data, dict):

        return jsonify({
            "status": "error",
            "message": "A valid JSON object is required."
        }), 400

    valid, message = validate_medication_schedule(data)

    if not valid:

        return jsonify({
            "status": "error",
            "message": message
        }), 400

    schedule = {

        "schedule_id": str(uuid.uuid4()),

        "medication_name": data["medication_name"].strip(),

        "dosage": data["dosage"].strip(),

        "frequency": data["frequency"].strip(),

        "reminder_times": data["reminder_times"],

        "before_or_after_food": data["before_or_after_food"],

        "start_date": data["start_date"],

        "end_date": data["end_date"],

        "confirmed": True,

        "active": True,

        "created_at": datetime.now().isoformat()
    }

    with schedule_lock:

        medication_schedules.append(schedule)

        save_medication_schedules()

    return jsonify({

        "status": "saved",

        "message": (
            "Medication schedule saved and activated."
        ),

        "schedule": schedule

    }), 201


# ==================================================
# CHAT API - OLLAMA
# ==================================================

@app.route(
    "/api/chat",
    methods=["POST"]
)
def medication_chat():

    data = request.get_json(silent=True) or {}

    message = data.get(
        "message",
        ""
    ).strip()

    if not message:

        return jsonify({
            "status": "error",
            "message": "Please enter a message."
        }), 400

    with schedule_lock:

        active_schedules = [

            {
                "medication_name": item.get("medication_name"),

                "dosage": item.get("dosage"),

                "frequency": item.get("frequency"),

                "reminder_times": item.get("reminder_times", []),

                "meal_instruction": MEAL_LABELS.get(
                    item.get("before_or_after_food"),
                    "Not specified"
                ),

                "start_date": item.get("start_date"),

                "end_date": item.get("end_date")

            }

            for item in medication_schedules

            if item.get("active")
        ]

    system_prompt = (
        "You are a helpful medication reminder assistant. "
        "Answer in simple, clear language. "
        "Use the saved medication schedule when answering questions. "
        "Never diagnose medical conditions. "
        "Never invent medication doses or instructions. "
        "Never change a prescribed dosage or schedule. "
        "For medical changes, advise the user to contact their doctor "
        "or pharmacist. "
        "Do not claim a medicine was taken unless the system confirms it. "
    )

    context = (
        "\nSaved medication schedules:\n"
        + json.dumps(active_schedules, indent=2)
    )

    try:

        response = requests.post(

            OLLAMA_URL,

            json={

                "model": OLLAMA_MODEL,

                "stream": False,

                "messages": [

                    {
                        "role": "system",
                        "content": system_prompt + context
                    },

                    {
                        "role": "user",
                        "content": message
                    }

                ],

                "options": {
                    "num_predict": 300
                }

            },

            timeout=60
        )

        response.raise_for_status()

        result = response.json()

        answer = result.get(
            "message",
            {}
        ).get(
            "content",
            "I could not generate a response."
        ).strip()

        return jsonify({

            "status": "success",

            "reply": answer

        }), 200

    except requests.exceptions.RequestException as error:

        print("Ollama connection error:", error)

        return jsonify({

            "status": "error",

            "message": (
                "Could not connect to Ollama. "
                "Please check that Ollama is running "
                "and qwen2.5-coder:7b is installed."
            )

        }), 503


# ==================================================
# TEST N8N WEBHOOK
# ==================================================

@app.route(
    "/test-n8n",
    methods=["GET"]
)
def test_n8n():

    success = send_n8n_notification(
        slot="test",
        alert_type="MISSED",
        missed_count=1,
        scheduled_time="09:00"
    )

    if success:

        return jsonify({
            "status": "success",
            "message": "Test event sent to n8n."
        }), 200

    return jsonify({
        "status": "error",
        "message": "Could not send test event to n8n."
    }), 500


# ==================================================
# MANUAL REMINDER ENDPOINT
# ==================================================

@app.route(
    "/remind",
    methods=["POST"]
)
def remind():

    data = request.get_json(silent=True) or {}

    slot = data.get(
        "slot",
        "manual"
    )

    with schedule_lock:

        schedule = next(
            (
                item for item in medication_schedules
                if item.get("active") is True
                and item.get("confirmed") is True
            ),
            None
        )

    if schedule is None:

        return jsonify({
            "status": "error",
            "message": "No active medication schedule found."
        }), 400

    with reminder_lock:

        if slot in active_reminders:

            return jsonify({
                "status": "already_active",
                "message": "This reminder is already running."
            }), 200

        session_id = str(uuid.uuid4())

        active_reminders[slot] = session_id

    current_time = datetime.now().strftime("%H:%M")

    threading.Thread(
        target=reminder_loop,
        args=(
            slot,
            session_id,
            schedule,
            current_time
        ),
        daemon=True
    ).start()

    return jsonify({

        "status": "started",

        "message": "Medication reminder started.",

        "scheduled_time": current_time,

        "repeat_interval_seconds": REPEAT_INTERVAL_SECONDS

    }), 200


# ==================================================
# HEALTH CHECK
# ==================================================

@app.route(
    "/",
    methods=["GET"]
)
def home():

    with reminder_lock:

        current_reminders = list(
            active_reminders.keys()
        )

    return jsonify({

        "status": "running",

        "message": (
            "Voice Medication Reminder Agent is running."
        ),

        "repeat_interval_seconds": REPEAT_INTERVAL_SECONDS,

        "active_reminders": current_reminders

    }), 200


# ==================================================
# START APPLICATION
# ==================================================

if __name__ == "__main__":

    load_medication_schedules()

    scheduler_thread = threading.Thread(
        target=medication_scheduler,
        daemon=True,
        name="MedicationScheduler"
    )

    scheduler_thread.start()

    print("------------------------------------")
    print("VOICE MEDICATION REMINDER AGENT")
    print("------------------------------------")

    print(
        "Repeat interval:",
        REPEAT_INTERVAL_SECONDS,
        "seconds"
    )

    print(
        "Maximum attempts:",
        MAX_REMINDER_ATTEMPTS
    )

    print(
        "Ollama model:",
        OLLAMA_MODEL
    )

    print(
        "n8n webhook:",
        N8N_MISSED_WEBHOOK_URL
    )

    print("------------------------------------")

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        use_reloader=False
    )

