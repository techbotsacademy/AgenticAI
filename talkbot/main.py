
import csv
import os
import time
import threading
import uuid
from datetime import datetime

import requests
import pyttsx3
import speech_recognition as sr
from flask import Flask, request, jsonify

app = Flask(__name__)

# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

# TEST MODE: repeat voice reminder every 10 seconds.
# Change this to 900 for 15 minutes after testing.
REPEAT_INTERVAL_SECONDS = 10
REPEAT_INTERVAL_MINUTES = REPEAT_INTERVAL_SECONDS / 60

MAX_REMINDER_ATTEMPTS = 3

# Send an urgent event after 3 consecutive missed cycles.
URGENT_AFTER_MISSED_CYCLES = 3

REMINDER_MESSAGE = (
    "Hello. It is time to take your medication. "
    "Please take your medication and let me know when you are done."
)

HISTORY_FILE = "medication_history.csv"

# --------------------------------------------------
# N8N CONFIGURATION
# --------------------------------------------------

# Use the production webhook URL when the n8n workflow is active.
N8N_MISSED_WEBHOOK_URL = "http://localhost:5678/webhook/medication-missed"

USER_ID = "USER001"
MEDICATION_NAME = "Inhaler"
CAREGIVER_CHAT_ID = "6241692378"

# --------------------------------------------------
# GLOBAL VARIABLES
# --------------------------------------------------

active_reminders = {}
consecutive_missed_cycles = {}

reminder_lock = threading.Lock()


# --------------------------------------------------
# N8N NOTIFICATION
# --------------------------------------------------

def send_n8n_notification(slot, alert_type, missed_count):
    """
    Send a missed-reminder event to n8n.

    n8n is responsible for sending Telegram notifications.
    Python does not directly send Telegram messages.
    """

    payload = {
        "user_id": USER_ID,
        "medication": MEDICATION_NAME,
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

def reminder_loop(slot, session_id):

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

                speak(REMINDER_MESSAGE)

                response = listen_for_response()

                if is_confirmed(response):

                    speak(
                        "Thank you. Your medication "
                        "has been marked as taken."
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
                        "I did not understand. Please say yes "
                        "after taking your medication."
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

            # Send one normal missed event to n8n.
            send_n8n_notification(
                slot=slot,
                alert_type="MISSED",
                missed_count=missed_count
            )

            log_reminder(
                slot,
                "MISSED_EVENT_SENT_TO_N8N",
                str(missed_count)
            )

            # After 3 consecutive missed cycles,
            # send an additional urgent event to n8n.
            if (
                missed_cycles_this_session
                >= URGENT_AFTER_MISSED_CYCLES
            ):

                print(
                    "Three consecutive reminder cycles missed. "
                    "Sending URGENT event to n8n."
                )

                urgent_sent = send_n8n_notification(
                    slot=slot,
                    alert_type="URGENT",
                    missed_count=missed_count
                )

                if urgent_sent:

                    log_reminder(
                        slot,
                        "URGENT_EVENT_SENT_TO_N8N",
                        str(missed_count)
                    )

                # Allow another urgent event after
                # another 3 missed cycles.
                missed_cycles_this_session = 0

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

    reminder_thread = threading.Thread(
        target=reminder_loop,
        args=(slot, session_id),
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
