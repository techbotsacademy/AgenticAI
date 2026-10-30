import csv
import os
import time
import threading
import uuid
from datetime import datetime

import pyttsx3
import speech_recognition as sr
from flask import Flask, request, jsonify


app = Flask(__name__)

# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

# Reminder repeats every 1 minute if not confirmed
REPEAT_INTERVAL_MINUTES = 15
REPEAT_INTERVAL_SECONDS = REPEAT_INTERVAL_MINUTES * 60

# Medication reminder message
REMINDER_MESSAGE = (
    "Hello. It is time to take your medication. "
    "Please take your medication and let me know when you are done."
)

# CSV file for storing reminder history
HISTORY_FILE = "medication_history.csv"

# Prevent duplicate reminder loops for the same slot
active_reminders = {}

# Lock to safely manage active reminders
reminder_lock = threading.Lock()


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
    """
    Listen for a spoken response.

    Returns the recognized text, or an empty string
    if no response is detected.
    """
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
# CHECK CONFIRMATION
# --------------------------------------------------

def is_confirmed(response):
    """Check whether the person confirmed taking medication."""

    confirmation_words = [
        "yes",
        "taken",
        "i took it",
        "done",
        "finished",
        "completed",
        "i have taken",
        "medicine taken",
        "medication taken"
    ]

    return any(
        word in response
        for word in confirmation_words
    )


# --------------------------------------------------
# SAVE REMINDER HISTORY
# --------------------------------------------------

def log_reminder(slot, status, response=""):
    """Save reminder status to a CSV file."""

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
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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
    Repeatedly remind the person every 1 minute
    until they confirm taking the medication.
    """

    print(f"Reminder started for slot: {slot}")

    try:
        while True:

            # Speak reminder
            speak(REMINDER_MESSAGE)

            # Listen for the person's response
            response = listen_for_response()

            # Check whether medication was confirmed
            if is_confirmed(response):

                speak(
                    "Thank you. Your medication has been marked as taken."
                )

                log_reminder(
                    slot,
                    "CONFIRMED",
                    response
                )

                print(
                    f"Medication confirmed for slot: {slot}"
                    )

                break

            elif response:
                speak(
                    "I did not understand. "
                    "Please say yes after taking your medication."
                )

                log_reminder(
                    slot,
                    "UNCLEAR",
                    response
                )

            else:
                speak(
                    f"I will remind you again in "
                f"{REPEAT_INTERVAL_MINUTES} minute."
                )

                log_reminder(
                    slot,
                    "NO_RESPONSE"
                )

            # Wait for the configured repeat interval
            print(
                f"Next reminder in "
                f"{REPEAT_INTERVAL_MINUTES} minute."
            )

            time.sleep(REPEAT_INTERVAL_SECONDS)

    except Exception as error:
        print(f"Reminder loop error: {error}")

        log_reminder(
            slot,
            "ERROR",
            str(error)
        )

    finally:
        # Remove reminder from active list
        with reminder_lock:
            if active_reminders.get(slot) == session_id:
                del active_reminders[slot]

        print(f"Reminder stopped for slot: {slot}")


# --------------------------------------------------
# N8N REMINDER ENDPOINT
# --------------------------------------------------

@app.route("/remind", methods=["POST"])
def remind():

    data = request.get_json(silent=True) or {}

    slot = data.get("slot", "default")

    # Prevent multiple active reminder loops
    # for the same slot
    with reminder_lock:

        if slot in active_reminders:

            return jsonify({
                "status": "already_active",
                "message": (
                    f"A reminder for {slot} "
                    f"is already running."
                ),
                "slot": slot,
                "repeat_interval_minutes": (
                    REPEAT_INTERVAL_MINUTES
                )
            }), 200

        session_id = str(uuid.uuid4())

        active_reminders[slot] = session_id

    # Run reminder loop in a background thread
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
            f"If no response is received, "
            f"I will remind you again in "
            f"{REPEAT_INTERVAL_MINUTES} minute."
        ),
        "slot": slot,
        "repeat_interval_minutes": (
            REPEAT_INTERVAL_MINUTES
        )
    }), 200


# --------------------------------------------------
# HEALTH CHECK
# --------------------------------------------------

@app.route("/", methods=["GET"])
def home():

    return jsonify({
        "status": "running",
        "message": "Voice Medication Reminder Agent is running.",
        "repeat_interval_minutes": (
            REPEAT_INTERVAL_MINUTES
        ),
        "active_reminders": list(
            active_reminders.keys()
        )
    }), 200


# --------------------------------------------------
# RUN FLASK APP
# --------------------------------------------------

if __name__ == "__main__":

    print("Starting Voice Medication Reminder Agent...")
    print(
        f"Reminder repeat interval: "
        f"{REPEAT_INTERVAL_MINUTES} minute"
    )

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        use_reloader=False
    )