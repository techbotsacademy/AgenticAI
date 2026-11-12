
import csv
import os
import time
import threading
import uuid
from datetime import datetime, timedelta
import json
import requests
import pyttsx3
import speech_recognition as sr
from flask import Flask, request, jsonify
from flask_cors import CORS
app = Flask(__name__)
CORS(app)
# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

# TEST MODE: repeat voice reminder every 10 seconds.
# Change this to 900 for 15 minutes after testing.
REPEAT_INTERVAL_SECONDS = 10
REPEAT_INTERVAL_MINUTES = REPEAT_INTERVAL_SECONDS / 60

MAX_REMINDER_ATTEMPTS = 3

# Send an urgent event after 3 consecutive missed cycles.
URGENT_AFTER_MISSED_CYCLES = 1

def get_reminder_message(schedule):

    hour = datetime.now().hour

    if hour < 12:
        greeting = "Good morning"
    elif hour < 17:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"

    meal_instructions = {
        "before_meal": "Please take it before your meal.",
        "after_meal": "Please take it after your meal.",
        "with_meal": "Please take it with your meal.",
        "anytime": "There are no specific meal instructions configured."
    }

    meal_timing = schedule.get(
        "before_or_after_food",
        "Not specified"
    )

    meal_message = meal_instructions.get(
        meal_timing,
        "Please follow your doctor's meal instructions."
    )

    return (
        f"{greeting}, {USER_NAME}! "
        f"It's time to take your "
        f"{schedule['medication_name']}, "
        f"{schedule['dosage']}. "
        f"{meal_message} "
        "Please let me know once you have taken it."
    )
# --------------------------------------------------
# MEDICATION SCHEDULE PERSISTENCE
# --------------------------------------------------
SCHEDULE_FILE = "medication_schedules.json"
medication_schedules = []
schedule_lock = threading.RLock()

def load_medication_schedules():
    global medication_schedules
    if not os.path.exists(SCHEDULE_FILE):
        medication_schedules = []
        return

    try:
        with open(SCHEDULE_FILE, "r", encoding="utf-8") as file:
            medication_schedules = json.load(file)

        if not isinstance(medication_schedules, list):
            raise ValueError("Schedule file must contain a JSON list.")

        print(
            f"Loaded {len(medication_schedules)} medication schedules."
        )

    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"Could not load medication schedules: {error}")
        medication_schedules = []


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

        os.replace(temporary_file, SCHEDULE_FILE)


        # --------------------------------------------------
# MEDICATION SCHEDULE VALIDATION
# --------------------------------------------------

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

    return True, "Schedule validation successful."
# --------------------------------------------------
# N8N CONFIGURATION
# --------------------------------------------------

# Use the production webhook URL when the n8n workflow is active.
N8N_MISSED_WEBHOOK_URL = "http://localhost:5678/webhook/medication-missed"

USER_ID = "USER001"
USER_NAME = "Keerthana"
MEDICATION_NAME = "Inhaler"
# Medication meal instructions
MEAL_TIMING = "after_meal"
# Medication course duration
MEDICATION_DURATION_DAYS = 7
MEDICATION_START_DATE = datetime.now().date()
MEDICATION_END_DATE = (
    MEDICATION_START_DATE +
    timedelta(days=MEDICATION_DURATION_DAYS)
)
CAREGIVER_CHAT_ID = "6241692378"
# --------------------------------------------------
# MEDICATION COURSE VALIDATION
# --------------------------------------------------

def is_medication_course_active(schedule):
    today = datetime.now().date()

    start_date = datetime.strptime(
        schedule["start_date"], "%Y-%m-%d"
    ).date()

    end_date = datetime.strptime(
        schedule["end_date"], "%Y-%m-%d"
    ).date()

    return start_date <= today <= end_date

# --------------------------------------------------
# GLOBAL VARIABLES
# --------------------------------------------------

active_reminders = {}
consecutive_missed_cycles = {}

reminder_lock = threading.Lock()


# --------------------------------------------------
# N8N NOTIFICATION
# --------------------------------------------------

def send_n8n_notification(slot, alert_type, missed_count, schedule=None):
    """
    Send a missed-reminder event to n8n.

    n8n is responsible for sending Telegram notifications.
    Python does not directly send Telegram messages.
    """

    payload = {
        "user_id": USER_ID,
        "medication": (
                schedule["medication_name"]
                if schedule else MEDICATION_NAME
            ),
            "dosage": (
                schedule["dosage"]
                if schedule else "Not specified"
            ),
        "slot": slot,
        "status": "missed",
        "alert_type": alert_type,
        "missed_count": missed_count,
        "caregiver_telegram_id": CAREGIVER_CHAT_ID,
        "timestamp": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    }

    try:
        print(
            f"Sending {alert_type} event to n8n "
            f"for {slot} reminder..."
        )

        response = requests.post(
            N8N_MISSED_WEBHOOK_URL,
            json=payload,
            timeout=10
        )

        response.raise_for_status()

        print(
            f"{alert_type} event successfully received by n8n."
        )

        return True

    except requests.exceptions.RequestException as error:

        print(f"Could not send event to n8n: {error}")

        return False


# --------------------------------------------------
# TEXT TO SPEECH
# --------------------------------------------------

def speak(message):
    """Speak a message using the laptop's speaker."""

    try:
        engine = pyttsx3.init()

        engine.setProperty("rate", 160)
        engine.setProperty("volume", 1.0)

        engine.say(message)
        engine.runAndWait()
        engine.stop()

    except Exception as error:
        print(f"TTS error: {error}")


# --------------------------------------------------
# SPEECH RECOGNITION
# --------------------------------------------------

def listen_for_response(timeout=8, phrase_time_limit=8):
    """Listen for a spoken response and return recognized text."""

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

        print(f"Recognized response: {response}")

        return response.lower().strip()

    except sr.WaitTimeoutError:

        print("No speech detected.")
        return ""

    except sr.UnknownValueError:

        print("Could not understand the response.")
        return ""

    except sr.RequestError as error:

        print(f"Speech recognition service error: {error}")
        return ""

    except Exception as error:

        print(f"Microphone error: {error}")
        return ""


# --------------------------------------------------
# CONFIRMATION
# --------------------------------------------------

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


# --------------------------------------------------
# HISTORY
# --------------------------------------------------
HISTORY_FILE = "reminder_history.csv"
def log_reminder(slot, status, response=""):

    file_exists = os.path.exists(HISTORY_FILE)

    try:
        with open(
            HISTORY_FILE,
            mode="a",
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

        print(f"CSV logging error: {error}")


# --------------------------------------------------
# REMINDER LOOP
# --------------------------------------------------

def reminder_loop(slot, session_id, schedule):
    """
    Reminder workflow:

    1. Speak and listen up to 3 times.
    2. Wait 10 seconds between attempts.
    3. If all 3 attempts are missed, send MISSED event to n8n.
    4. After 3 consecutive missed cycles, send URGENT event.
    5. Continue until medication is confirmed.
    """

    print(f"Reminder started for slot: {slot}")

    missed_cycles_this_session = 0

    try:

        while True:

            # Stop reminders when the medication course is completed.
            if not is_medication_course_active(schedule):

                speak(
                    f"{USER_NAME}, your prescribed medication course "
                    "has reached its end date. Reminders have been stopped."
                )

                log_reminder(
                    slot,
                    "COURSE_COMPLETED",
                    "Medication duration completed"
                )

                print("Medication course completed. Stopping reminders.")
                return

            confirmed = False

            # One cycle = 3 voice reminder attempts.
            for attempt in range(
                1,
                MAX_REMINDER_ATTEMPTS + 1
            ):

                print(
                    f"Reminder attempt {attempt}/"
                    f"{MAX_REMINDER_ATTEMPTS} for {slot}"
                )

                speak(get_reminder_message(schedule))

                response = listen_for_response()

                if is_confirmed(response):

                    speak(
                        f"Well done, {USER_NAME}! "
                        f"Your {schedule['medication_name']} ({schedule['dosage']}) has been marked as taken. "
                    )

                    log_reminder(
                        slot,
                        "CONFIRMED",
                        response
                    )

                    with reminder_lock:
                        consecutive_missed_cycles[slot] = 0

                    print(
                        f"Medication confirmed for slot: {slot}"
                    )

                    confirmed = True
                    break

                if response:

                    speak(
                        f"{USER_NAME}, I didn't quite understand. "
                        f"Please confirm once you have taken your {schedule['medication_name']}."
                    )

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

                    print(
                        "Next voice reminder in "
                        f"{REPEAT_INTERVAL_MINUTES:.2f} minutes."
                    )

                    time.sleep(REPEAT_INTERVAL_SECONDS)

            # Stop when medication is confirmed.
            if confirmed:
                return

            # All 3 voice attempts were missed.
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

            print(
                "Reminder cycle missed. "
                f"Consecutive missed cycles: {missed_count}"
            )
            speak(
                f"{USER_NAME}, I haven't received your confirmation "
                f"for your {schedule['medication_name']} yet. "
                "Please let me know once you have taken it."
            )

            # Send one normal missed event to n8n.
            
            send_n8n_notification(
                slot=slot,
                alert_type="MISSED",
                missed_count=missed_count,
                schedule=schedule
            )

            log_reminder(
                slot,
                "MISSED_EVENT_SENT_TO_N8N",
                str(missed_count)
            )

            # After 3 unanswered voice attempts, send one urgent alert and stop.
            if (
                missed_cycles_this_session
                >= URGENT_AFTER_MISSED_CYCLES
            ):

                print(
                    "Three voice reminder attempts missed. "
                    "Sending URGENT event to n8n."
                )

                speak(
                    f"{USER_NAME}, I haven't received your confirmation "
                    f"for your {schedule['medication_name']}. "
                    "I will share this with your father so he can check on you."
                )

                urgent_sent = send_n8n_notification(
                    slot=slot,
                    alert_type="URGENT",
                    missed_count=missed_count,
                    schedule=schedule
                )

                if urgent_sent:
                    log_reminder(
                        slot,
                        "URGENT_EVENT_SENT_TO_N8N",
                        str(missed_count)
                    )
                    print("Urgent notification sent successfully.")
                else:
                    print("Urgent notification could not be sent.")

                # Stop this reminder session.
                return


           

    except Exception as error:

        print(f"Reminder loop error: {error}")

        log_reminder(
            slot,
            "ERROR",
            str(error)
        )

    finally:

        with reminder_lock:

            if active_reminders.get(slot) == session_id:
                del active_reminders[slot]

        print(f"Reminder stopped for slot: {slot}")

# --------------------------------------------------
# AUTOMATIC MEDICATION SCHEDULER
# --------------------------------------------------

SCHEDULER_CHECK_INTERVAL = 5

scheduled_reminder_runs = set()


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

                if current_time not in schedule.get("reminder_times", []):
                    continue

                schedule_id = schedule.get("schedule_id")

                run_id = f"{schedule_id}_{today}_{current_time}"

                if run_id in scheduled_reminder_runs:
                    continue

                slot = f"medication_{schedule_id}"

                with reminder_lock:

                    if slot in active_reminders:
                        continue

                    session_id = str(uuid.uuid4())
                    active_reminders[slot] = session_id

                scheduled_reminder_runs.add(run_id)

                print(
                    f"Starting automatic reminder: "
                    f"{schedule.get('medication_name')}"
                )

                threading.Thread(
                    target=reminder_loop,
                    args=(slot, session_id, schedule),
                    daemon=True
                ).start()

        except Exception as error:

            print(f"Scheduler error: {error}")

        time.sleep(SCHEDULER_CHECK_INTERVAL)
# --------------------------------------------------
# RECEIVE CONFIRMED MEDICATION SCHEDULES
# --------------------------------------------------

@app.route("/api/medications", methods=["POST"])
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
        "before_or_after_food": data.get(
            "before_or_after_food", "Not specified"
        ),
        "start_date": data["start_date"],
        "end_date": data["end_date"],
        "confirmed": True,
        "active": True,
        "created_at": datetime.now().isoformat()
    }

    with schedule_lock:
        medication_schedules.append(schedule)
        save_medication_schedules()

    return jsonify(
        {
        "status": "saved",
        "message": "Medication schedule saved and activated successfully.",
        "schedule": schedule
    }), 201


# --------------------------------------------------
# TEST N8N WEBHOOK ENDPOINT
# --------------------------------------------------

@app.route(
    "/test-n8n",
    methods=["GET"]
)
def test_n8n():

    success = send_n8n_notification(
        slot="test",
        alert_type="MISSED",
        missed_count=1
    )

    if success:

        return jsonify({
            "status": "success",
            "message": (
                "Test missed-reminder event "
                "successfully sent to n8n."
            )
        }), 200

    return jsonify({
        "status": "error",
        "message": (
            "Could not send test event to n8n. "
            "Check the webhook URL and n8n workflow."
        )
    }), 500


# --------------------------------------------------
# REMINDER ENDPOINT
# --------------------------------------------------

@app.route(
    "/remind",
    methods=["POST"]
)
def remind():

    data = request.get_json(silent=True) or {}

    slot = data.get(
        "slot",
        "default"
    )

    with reminder_lock:

        if slot in active_reminders:

            return jsonify({
                "status": "already_active",
                "message": (
                    f"A reminder for {slot} "
                    "is already running."
                ),
                "slot": slot,
                "repeat_interval_seconds": (
                    REPEAT_INTERVAL_SECONDS
                )
            }), 200

        session_id = str(uuid.uuid4())

        active_reminders[slot] = session_id

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
            with reminder_lock:
                active_reminders.pop(slot, None)

            return jsonify({
                "status": "error",
                "message": "No active confirmed medication schedule found."
            }), 400

        reminder_thread = threading.Thread(
            target=reminder_loop,
            args=(slot, session_id, schedule),
            daemon=True
        )

        reminder_thread.start()


    return jsonify({

        "status": "started",

        "message": (
            f"Reminder started for {slot}. "
            f"It will repeat every "
            f"{REPEAT_INTERVAL_SECONDS} seconds. "
            "After 3 missed voice attempts, "
            "a missed event will be sent to n8n."
        ),

        "slot": slot,

        "repeat_interval_seconds": (
            REPEAT_INTERVAL_SECONDS
        ),

        "max_reminder_attempts": (
            MAX_REMINDER_ATTEMPTS
        ),

        "urgent_after_missed_cycles": (
            URGENT_AFTER_MISSED_CYCLES
        )

    }), 200


# --------------------------------------------------
# HEALTH CHECK
# --------------------------------------------------

@app.route(
    "/",
    methods=["GET"]
)
def home():

    with reminder_lock:
        current_reminders = list(active_reminders.keys())

    return jsonify({

        "status": "running",

        "message": (
            "Voice Medication Reminder Agent is running."
        ),

        "repeat_interval_seconds": (
            REPEAT_INTERVAL_SECONDS
        ),

        "max_reminder_attempts": (
            MAX_REMINDER_ATTEMPTS
        ),

        "active_reminders": current_reminders

    }), 200


# --------------------------------------------------
# RUN FLASK
# --------------------------------------------------

if __name__ == "__main__":

    load_medication_schedules()
    scheduler_thread = threading.Thread(
    target=medication_scheduler,
    daemon=True,
    name="MedicationScheduler"
)

    scheduler_thread.start()
    print(
        "Starting Voice Medication Reminder Agent..."
    )

    print(
        f"Reminder repeat interval: "
        f"{REPEAT_INTERVAL_SECONDS} seconds"
    )

    print(
        f"Maximum voice reminder attempts: "
        f"{MAX_REMINDER_ATTEMPTS}"
    )

    print(
        f"n8n webhook: {N8N_MISSED_WEBHOOK_URL}"
    )

    print(
        "Telegram notifications are handled by n8n."
    )

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        use_reloader=False
    )
