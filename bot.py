import os
import io
import sqlite3
import uuid
import logging
import textwrap
import urllib.request
from dotenv import load_dotenv
from groq import Groq
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from PIL import Image, ImageDraw, ImageFont
import edge_tts

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0")) if os.getenv("CHANNEL_ID") else 0
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/TheRoastClinic")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def find_font(filename):
    for p in [filename, f"./{filename}", f"fonts/{filename}", os.path.join(os.path.dirname(__file__), filename)]:
        if os.path.exists(p):
            return p
    return None

def ensure_fonts():
    fonts = {
        "Montserrat-Bold.ttf": "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat-Bold.ttf",
        "Montserrat-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat-Regular.ttf",
        "Montserrat-Italic.ttf": "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat-Italic.ttf",
    }
    os.makedirs("fonts", exist_ok=True)
    for name, url in fonts.items():
        if not find_font(name):
            try:
                print(f"Downloading {name}...")
                urllib.request.urlretrieve(url, name)
            except Exception as e:
                print(f"Failed {name}: {e}")

ensure_fonts()

conn = sqlite3.connect("roasts.db", check_same_thread=False)
cur = conn.cursor()
cur.execute("""CREATE TABLE IF NOT EXISTS roasts (id TEXT PRIMARY KEY, confession TEXT, roast TEXT, style TEXT, votes INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
cur.execute("""CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, last_confession TEXT)""")
conn.commit()

STYLES = {
    "PIDGIN": {"name": "🇳🇬 Pidgin Specialist", "prompt": "Roast in Nigerian Pidgin English. Savage, street, funny. Keep under 40 words.", "voice": "en-NG-EzinneNeural"},
    "AMERICAN": {"name": "🇺🇸 American Bestie", "prompt": "Roast in Gen Z American slang, savage bestie vibe, deadpan. Under 40 words.", "voice": "en-US-AriaNeural"},
    "BRITISH": {"name": "🇬🇧 British Doctor", "prompt": "Roast in dry British sarcasm, polite but deadly. Under 40 words.", "voice": "en-GB-SoniaNeural"},
    "PASTOR": {"name": "⛪ Pastor Doctor", "prompt": "Roast like a dramatic Nigerian pastor preaching. Holy ghost fire. Under 40 words.", "voice": "en-NG-EzinneNeural"},
    "NAIJAMOM": {"name": "👩‍🦳 Naija Mom Doctor", "prompt": "Roast like a Nigerian mother, dramatic, disappointed. Under 40 words.", "voice": "en-NG-EzinneNeural"},
    "USMOM": {"name": "👱‍♀️ US Mom Doctor", "prompt": "Roast like a passive aggressive American mom, bless your heart. Under 40 words.", "voice": "en-US-JennyNeural"},
    "POET": {"name": "🎤 Poet Doctor", "prompt": "Roast in poetic form, rhythmic, savage. Under 40 words.", "voice": "en-US-GuyNeural"},
    "AI": {"name": "🤖 AI Doctor", "prompt": "Roast as a tired AI fed up with humans. Under 40 words.", "voice": "en-US-GuyNeural"},
    "MOTIV": {"name": "💪 Motiv Doctor", "prompt": "Roast as fake motivational speaker, toxic positivity savage. Under 40 words.", "voice": "en-US-DavisNeural"},
    "SHAKESPEARE": {"name": "📜 Shakespeare", "prompt": "Roast in Shakespearean English, thou art foolish. Under 40 words.", "voice": "en-GB-RyanNeural"},
}

BASE_PROMPT = "You are Dr. Roaster at The Roast Clinic. Roast the CONFESSION, not the person. Savage, witty, funny. Under 40 words. Confession: {confession} Style: {style_prompt} Roast:"
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

def get_roast(confession, style_key):
    style = STYLES.get(style_key, STYLES["AMERICAN"])
    prompt = BASE_PROMPT.format(confession=confession, style_prompt=style["prompt"])
    try:
        chat = groq_client.chat.completions.create(model="llama-3.1-8b-instant", messages=[{"role": "user", "content": prompt}], temperature=0.85, max_tokens=150)
        return chat.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Groq error: {e}")
        return "Clinic closed! Dr. Roaster fainted. Try again 😭"

def load_font_safe(name, size):
    path = find_font(name)
    if path:
        try: return ImageFont.truetype(path, size)
        except: pass
    return ImageFont.load_default()

# NEW: IN-MEMORY IMAGE - NO DISK
def make_card(confession, roast, style_key):
    W, H = 1080, 1350
    img = Image.new("RGB", (W, H), "#0f0f0f")
    draw = ImageDraw.Draw(img)
    for y in range(H):
        r = int(15 + y * 0.15); g = int(15 + y * 0.05); b = int(30 + y * 0.12)
        draw.line([(0, y), (W, y)], fill=(min(r,80), min(g,40), min(b,120)))
    bold = load_font_safe("Montserrat-Bold.ttf", 62)
    regular = load_font_safe("Montserrat-Regular.ttf", 38)
    italic = load_font_safe("Montserrat-Italic.ttf", 32)
    draw.text((60, 100), textwrap.fill(f'"{confession}"', width=32), font=italic, fill="#b0b0b0")
    draw.text((60, 400), textwrap.fill(roast, width=28), font=bold, fill="white", stroke_width=3, stroke_fill="black", spacing=12)
    draw.text((60, H-120), f"{style_key} ROAST | Dr. Roaster | {CHANNEL_LINK}", font=regular, fill="#ff8a00")
    bio = io.BytesIO()
    bio.name = f"roast_{uuid.uuid4().hex[:8]}.jpg"
    img.save(bio, "JPEG", quality=95)
    bio.seek(0)
    return bio

# NEW: IN-MEMORY VOICE - NO DISK
async def make_voice(text, style_key):
    voice = STYLES.get(style_key, STYLES["AMERICAN"])["voice"]
    communicate = edge_tts.Communicate(text, voice)
    audio_bio = io.BytesIO()
    audio_bio.name = f"voice_{uuid.uuid4().hex[:8]}.mp3"
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_bio.write(chunk["data"])
    audio_bio.seek(0)
    return audio_bio

async def is_joined(user_id, context):
    if CHANNEL_ID == 0: return True
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except: return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_joined(update.effective_user.id, context):
        kb = [[InlineKeyboardButton("🏥 Join Clinic First", url=CHANNEL_LINK)], [InlineKeyboardButton("✅ I Joined - Check", callback_data="check_join")]]
        await update.message.reply_text(f"🏥 Dr. Roaster is in!\n\nTo proceed, join:\n{CHANNEL_LINK}", reply_markup=InlineKeyboardMarkup(kb))
        return
    await update.message.reply_text("🏥 Dr. Roaster is in!\n\nSend confession starting with 'I...'\nExample: I still stalk my ex everyday")

async def join_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_joined(update.effective_user.id, context):
        await update.message.reply_text("✅ Admitted! Send confession starting with 'I...'")
    else:
        kb = [[InlineKeyboardButton("🏥 Join Clinic", url=CHANNEL_LINK)]]
        await update.message.reply_text(f"❌ You haven't joined. Join: {CHANNEL_LINK}", reply_markup=InlineKeyboardMarkup(kb))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id; text = update.message.text.strip()
    if not await is_joined(user_id, context):
        kb = [[InlineKeyboardButton("🏥 Join Clinic First", url=CHANNEL_LINK)]]
        await update.message.reply_text(f"❌ Join first: {CHANNEL_LINK}", reply_markup=InlineKeyboardMarkup(kb)); return
    if len(text) < 10: await update.message.reply_text("Too short. Example: I still stalk my ex..."); return
    if any(x in text.lower() for x in ["http://", "https://", "@", "+234", "kill myself", "suicide"]): await update.message.reply_text("❌ No links, @, numbers, or self-harm."); return
    context.user_data["pending_confession"] = text
    cur.execute("INSERT OR REPLACE INTO users (user_id, last_confession) VALUES (?, ?)", (user_id, text)); conn.commit()
    kb=[]; row=[]
    for key, data in STYLES.items():
        row.append(InlineKeyboardButton(data["name"], callback_data=f"roast_{key}"))
        if len(row)==2: kb.append(row); row=[]
    if row: kb.append(row)
    await update.message.reply_text(f"📝 Got it: \"{text}\"\n\nPick your doctor:", reply_markup=InlineKeyboardMarkup(kb))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data; user_id = query.from_user.id
    if data == "check_join":
        if await is_joined(user_id, context): await query.edit_message_text("✅ Admitted! Send confession starting with 'I...'")
        else: await query.edit_message_text(f"❌ Still not joined. Join: {CHANNEL_LINK}"); return
    if data.startswith("roast_"):
        if not await is_joined(user_id, context):
            kb=[[InlineKeyboardButton("🏥 Re-Join Clinic", url=CHANNEL_LINK)]]
            await query.edit_message_text(f"❌ You left! Re-join: {CHANNEL_LINK}", reply_markup=InlineKeyboardMarkup(kb)); return
        style_key = data.replace("roast_", "")
        confession = context.user_data.get("pending_confession")
        if not confession:
            cur.execute("SELECT last_confession FROM users WHERE user_id=?", (user_id,)); row=cur.fetchone(); confession=row[0] if row else None
        if not confession: await query.edit_message_text("Send confession first."); return
        await query.edit_message_text(f"🏥 Dr. {style_key} processing... 💉")
        if not await is_joined(user_id, context):
            kb=[[InlineKeyboardButton("🏥 Re-Join Clinic", url=CHANNEL_LINK)]]
            await query.edit_message_text(f"❌ You left! Re-join: {CHANNEL_LINK}", reply_markup=InlineKeyboardMarkup(kb)); return
        roast = get_roast(confession, style_key)
        card_bio = make_card(confession, roast, style_key)
        try: voice_bio = await make_voice(roast, style_key)
        except: voice_bio = None
        rid = uuid.uuid4().hex[:8]
        cur.execute("INSERT INTO roasts (id, confession, roast, style) VALUES (?, ?, ?, ?)", (rid, confession, roast, style_key)); conn.commit()
        if CHANNEL_ID != 0:
            try:
                await context.bot.send_photo(chat_id=CHANNEL_ID, photo=card_bio, caption=f"🏥 CASE #{rid} | Dr. {style_key}\n\n{roast}\n\nGet roasted: {CHANNEL_LINK.replace('https://t.me/', '@')}")
                if voice_bio:
                    voice_bio.seek(0); await context.bot.send_voice(chat_id=CHANNEL_ID, voice=voice_bio)
            except Exception as e: logger.error(f"Channel error: {e}")
        try:
            card_bio.seek(0); await context.bot.send_photo(chat_id=user_id, photo=card_bio, caption=f"✅ Posted anonymously\n\nYour roast: {roast}")
            if voice_bio: voice_bio.seek(0); await context.bot.send_voice(chat_id=user_id, voice=voice_bio)
        except Exception as e: logger.error(f"User send error: {e}")
        context.user_data.pop("pending_confession", None)

async def top_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cur.execute("SELECT id, roast FROM roasts ORDER BY votes DESC LIMIT 5"); rows=cur.fetchall()
    if not rows: await update.message.reply_text("No roasts yet!"); return
    msg="🏆 TOP 5:\n\n"
    for i,(rid, roast) in enumerate(rows,1): msg+=f"{i}. #{rid} - {roast[:60]}...\n\n"
    await update.message.reply_text(msg)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏥 Dr. Roaster Help\n/join - Check membership\n/top - Top 5\nSend confession with 'I...'")

def main():
    if not BOT_TOKEN: print("Missing BOT_TOKEN"); return
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start)); app.add_handler(CommandHandler("join", join_cmd)); app.add_handler(CommandHandler("top", top_cmd)); app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(button_handler)); app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🏥 Dr. Roaster Bot running..."); app.run_polling()

if __name__ == "__main__": main()