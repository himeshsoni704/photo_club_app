"""
telegram_gemini_auto_reply_full.py

Telegram auto-reply bot using Telethon + official Google Gemini streaming SDK.
- Uses generate_content_stream for AI replies
- Custom prompt style (Himesh's casual, friendly texting style)
- Handles multi-turn conversations
- Shutdown trigger with secret keyword by owner
"""

import asyncio
import sys
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from google import genai

# ---------------- CONFIG ----------------
api_id = 25280628
api_hash = "a661ce421f9fb2ff4a4a3107a7cffe3c"
session_name = "tg_gemini_full_session"

GEMINI_API_KEY = "AIzaSyC4OTVOiRz2t2D5MCO4sIaxRVey2pnD9KY"  # Replace with your key
MODEL_NAME = "gemini-2.5-flash"

MIN_REPLY_DELAY = 1.0
MAX_REPLY_DELAY = 2.0
CONTEXT_LINES = 6

ALLOWED_SENDERS = []  # leave empty to reply to everyone
OWNER_ID = 123456789  # <-- replace with your Telegram numeric ID
GLOBAL_SHUTDOWN_TRIGGER = "gup re"

# ---------------------------------------

# Custom prompt template for your texting style
PROMPT_TEMPLATE = """
You are Himesh. You reply like a human, in your personal texting style:
- Short sentences, casual, mix of English and Hinglish.
- Sometimes misspellings or playful typos.
- Playful
- Replies can be fragmented, interrupted
- Always sound natural, not a formal AI.
- Be short

Conversation history:
{history}

New message:
User: {new_message}
Assistant:
"""

# ---------------- TELEGRAM + GEMINI CLIENTS ----------------
client = TelegramClient(session_name, api_id, api_hash)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# Conversation history memory
conversations = {}  # {chat_id: [(role, text), ...]}


def add_to_conversation(chat_id, role, text):
    history = conversations.setdefault(chat_id, [])
    history.append((role, text))
    if len(history) > 50:
        history[:] = history[-50:]


async def call_gemini_api_stream(new_message, chat_id):
    """Uses Gemini streaming API to generate AI response in Himesh style."""
    chat_history = conversations.get(chat_id, [])[-CONTEXT_LINES:]
    history_text = ""
    for role, text in chat_history:
        if role == "user":
            history_text += f"User: {text}\n"
        else:
            history_text += f"Assistant: {text}\n"

    final_prompt = PROMPT_TEMPLATE.format(
        history=history_text,
        new_message=new_message
    )

    full_text = ""
    response_stream = gemini_client.models.generate_content_stream(
        model=MODEL_NAME,
        contents=[final_prompt]
    )
    for chunk in response_stream:
        full_text += chunk.text
    return full_text.strip()


def should_reply(event):
    """Optionally restrict replies to allowed senders."""
    if event.out:  # skip messages sent by yourself
        return False
    if ALLOWED_SENDERS:
        sender_id = getattr(event.sender, "id", None) or event.sender_id
        return sender_id in ALLOWED_SENDERS
    return True


@client.on(events.NewMessage(incoming=True))
async def handler(event):
    # debug: print incoming message info
    print(f"Incoming message: chat_id={event.chat_id}, sender_id={event.sender_id}, text={event.raw_text}")

    # fetch sender safely
    try:
        sender = await event.get_sender()
        sender_id = getattr(sender, "id", None)
        sender_username = getattr(sender, "username", None)
    except:
        sender_id = event.sender_id
        sender_username = None

    text = (event.raw_text or "").strip()
    if not text:
        return

    # --- Shutdown trigger ---
    if text.lower() == GLOBAL_SHUTDOWN_TRIGGER and sender_id == OWNER_ID:
        await event.respond("Ok 😭 gup re detected. Shutting down... bye! 💔")
        print("Shutdown triggered by owner. Exiting...")
        try:
            await client.disconnect()
        except:
            sys.exit(0)
        return
    elif text.lower() == GLOBAL_SHUTDOWN_TRIGGER:
        await event.respond("Hmm. OKAY 💔😔")
        return

    # check allowed senders
    if ALLOWED_SENDERS and sender_id not in ALLOWED_SENDERS:
        print(f"Skipping message from {sender_id} (not in ALLOWED_SENDERS).")
        return

    add_to_conversation(event.chat_id, "user", text)

    # simulate typing delay
    delay = MIN_REPLY_DELAY + (MAX_REPLY_DELAY - MIN_REPLY_DELAY) * min(1.0, len(text) / 200.0)
    await asyncio.sleep(delay)
    try:
        await client.send_chat_action(event.chat_id, "typing")
    except:
        pass

    try:
        reply_text = await call_gemini_api_stream(text, event.chat_id)
        add_to_conversation(event.chat_id, "assistant", reply_text)
        print("Reply from Gemini:\n", reply_text)

        await asyncio.sleep(0.5)
        await event.respond(reply_text)
        print(f"Replied to {sender_username or sender_id}.\n")

    except FloodWaitError as e:
        print(f"FloodWaitError: sleeping for {e.seconds} seconds")
        await asyncio.sleep(e.seconds)
        await event.respond(reply_text)
    except Exception as e:
        print("Error sending reply:", e)


def main():
    print("Starting Telegram client...")
    client.start()
    print("Client started. Listening for incoming messages...")
    client.run_until_disconnected()


if __name__ == "__main__":
    main()
