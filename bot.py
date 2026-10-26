import os, io, sqlite3, uuid, logging, textwrap, urllib.request
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
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def find_font(f):
    for p in [f, f"./{f}", f"fonts/{f}", os.path.join(os.path.dirname(__file__), f)]:
        if os.path.exists(p): return p
    return None
def ensure_fonts():
    for name, url in {
        "Montserrat-Bold.ttf": "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat-Bold.ttf",
        "Montserrat-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat-Regular.ttf",
        "Montserrat-Italic.ttf": "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat-Italic.ttf",
    }.items():
        if not find_font(name):
            try: urllib.request.urlretrieve(url, name)
            except: pass
ensure_fonts()

conn = sqlite3.connect("roasts.db", check_same_thread=False)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS roasts (id TEXT PRIMARY KEY, confession TEXT, roast TEXT, style TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, last_confession TEXT)")
conn.commit()

STYLES = {
    "PIDGIN": {"name": "🇳🇬 Pidgin Specialist", "prompt": "Roast in Nigerian Pidgin English. Savage, street, funny. Under 40 words.", "voice": "en-NG-EzinneNeural"},
    "AMERICAN": {"name": "🇺🇸 American Bestie", "prompt": "Roast in Gen Z American slang, savage bestie vibe. Under 40 words.", "voice": "en-US-AriaNeural"},
    "BRITISH": {"name": "🇬🇧 British Doctor", "prompt": "Roast in dry British sarcasm. Under 40 words.", "voice": "en-GB-SoniaNeural"},
    "PASTOR": {"name": "⛪ Pastor Doctor", "prompt": "Roast like dramatic Nigerian pastor. Under 40 words.", "voice": "en-NG-EzinneNeural"},
    "NAIJAMOM": {"name": "👩‍🦳 Naija Mom Doctor", "prompt": "Roast like Nigerian mother disappointed. Under 40 words.", "voice": "en-NG-EzinneNeural"},
    "USMOM": {"name": "👱‍♀️ US Mom Doctor", "prompt": "Roast like passive aggressive American mom. Under 40 words.", "voice": "en-US-JennyNeural"},
    "POET": {"name": "🎤 Poet Doctor", "prompt": "Roast in poetic form. Under 40 words.", "voice": "en-US-GuyNeural"},
    "AI": {"name": "🤖 AI Doctor", "prompt": "Roast as tired AI. Under 40 words.", "voice": "en-US-GuyNeural"},
    "MOTIV": {"name": "💪 Motiv Doctor", "prompt": "Roast as fake motivational speaker. Under 40 words.", "voice": "en-US-DavisNeural"},
    "SHAKESPEARE": {"name": "📜 Shakespeare", "prompt": "Roast in Shakespearean English. Under 40 words.", "voice": "en-GB-RyanNeural"},
}

BASE_PROMPT = "You are Dr. Roaster at The Roast Clinic. Roast the CONFESSION, not the person. Savage, funny. Under 40 words. Confession: {confession} Style: {style_prompt} Roast:"
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

def get_roast(confession, style_key):
    style = STYLES.get(style_key, STYLES["AMERICAN"])
    try:
        chat = groq_client.chat.completions.create(model="llama-3.1-8b-instant", messages=[{"role": "user", "content": BASE_PROMPT.format(confession=confession, style_prompt=style["prompt"])}], temperature=0.85, max_tokens=150)
        return chat.choices[0].message.content.strip()
    except: return "Clinic closed! Dr. Roaster fainted. Try again 😭"

def load_font_safe(name, size):
    p=find_font(name)
    if p:
        try: return ImageFont.truetype(p, size)
        except: pass
    return ImageFont.load_default()

def make_card(confession, roast, style_key):
    W,H=1080,1350
    img=Image.new("RGB",(W,H),"#0f0f0f"); draw=ImageDraw.Draw(img)
    for y in range(H):
        draw.line([(0,y),(W,y)], fill=(min(15+int(y*0.15),80), min(15+int(y*0.05),40), min(30+int(y*0.12),120)))
    bold=load_font_safe("Montserrat-Bold.ttf",62); reg=load_font_safe("Montserrat-Regular.ttf",38); it=load_font_safe("Montserrat-Italic.ttf",32)
    draw.text((60,100), textwrap.fill(f'"{confession}"',32), font=it, fill="#b0b0b0")
    draw.text((60,400), textwrap.fill(roast,28), font=bold, fill="white", stroke_width=3, stroke_fill="black", spacing=12)
    draw.text((60,H-120), f"{style_key} | Dr. Roaster | {CHANNEL_LINK}", font=reg, fill="#ff8a00")
    bio=io.BytesIO(); bio.name=f"roast_{uuid.uuid4().hex[:8]}.jpg"; img.save(bio,"JPEG",quality=95); bio.seek(0); return bio

async def make_voice(text, style_key):
    voice=STYLES.get(style_key, STYLES["AMERICAN"])["voice"]
    comm=edge_tts.Communicate(text, voice)
    bio=io.BytesIO(); bio.name=f"voice_{uuid.uuid4().hex[:8]}.mp3"
    async for chunk in comm.stream():
        if chunk["type"]=="audio": bio.write(chunk["data"])
    bio.seek(0); return bio

async def is_joined(uid, ctx):
    if CHANNEL_ID==0: return True
    try:
        m=await ctx.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=uid)
        return m.status in ["member","administrator","creator"]
    except: return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_joined(update.effective_user.id, context):
        kb=[[InlineKeyboardButton("🏥 Join Clinic First", url=CHANNEL_LINK)], [InlineKeyboardButton("✅ I Joined - Check", callback_data="check_join")]]
        await update.message.reply_text(f"🏥 Dr. Roaster is in!\n\nJoin first:\n{CHANNEL_LINK}", reply_markup=InlineKeyboardMarkup(kb)); return
    await update.message.reply_text("🏥 Dr. Roaster is in!\n\nSend confession starting with 'I...'")

async def join_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_joined(update.effective_user.id, context): await update.message.reply_text("✅ Admitted! Send confession with 'I...'")
    else:
        kb=[[InlineKeyboardButton("🏥 Join Clinic", url=CHANNEL_LINK)]]
        await update.message.reply_text(f"❌ Join first: {CHANNEL_LINK}", reply_markup=InlineKeyboardMarkup(kb))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id; text=update.message.text.strip()
    if not await is_joined(uid, context):
        kb=[[InlineKeyboardButton("🏥 Join Clinic First", url=CHANNEL_LINK)]]
        await update.message.reply_text(f"❌ Join first: {CHANNEL_LINK}", reply_markup=InlineKeyboardMarkup(kb)); return
    if len(text)<10: await update.message.reply_text("Too short."); return
    if any(x in text.lower() for x in ["http://","https://","@","+234","kill myself"]): await update.message.reply_text("❌ No links/@/numbers."); return
    context.user_data["pending"]=text
    cur.execute("INSERT OR REPLACE INTO users (user_id, last_confession) VALUES (?,?)",(uid,text)); conn.commit()
    kb=[]; row=[]
    for k,v in STYLES.items():
        row.append(InlineKeyboardButton(v["name"], callback_data=f"roast_{k}"))
        if len(row)==2: kb.append(row); row=[]
    if row: kb.append(row)
    await update.message.reply_text(f"📝 Got it: \"{text}\"\n\nPick doctor:", reply_markup=InlineKeyboardMarkup(kb))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer(); data=q.data; uid=q.from_user.id
    if data=="check_join":
        if await is_joined(uid, context): await q.edit_message_text("✅ Admitted! Send confession with 'I...'")
        else: await q.edit_message_text(f"❌ Still not joined: {CHANNEL_LINK}"); return
    if data.startswith("roast_"):
        style=data.replace("roast_","")
        confession=context.user_data.get("pending")
        if not confession:
            cur.execute("SELECT last_confession FROM users WHERE user_id=?",(uid,)); r=cur.fetchone(); confession=r[0] if r else None
        if not confession: await q.edit_message_text("Send confession first."); return
        await q.edit_message_text(f"🏥 Dr. {style} processing... 💉")
        roast=get_roast(confession, style)
        card=make_card(confession, roast, style)
        try: voice=await make_voice(roast, style)
        except: voice=None
        rid=uuid.uuid4().hex[:8]
        cur.execute("INSERT INTO roasts (id, confession, roast, style) VALUES (?,?,?,?)",(rid,confession,roast,style)); conn.commit()
        if CHANNEL_ID!=0:
            try:
                await context.bot.send_photo(chat_id=CHANNEL_ID, photo=card, caption=f"🏥 CASE #{rid} | Dr. {style}\n\n{roast}")
                if voice: voice.seek(0); await context.bot.send_voice(chat_id=CHANNEL_ID, voice=voice)
            except Exception as e: print(e)
        try:
            card.seek(0); await context.bot.send_photo(chat_id=uid, photo=card, caption=f"✅ Posted anonymously\n\n{roast}")
            if voice: voice.seek(0); await context.bot.send_voice(chat_id=uid, voice=voice)
        except: pass

def main():
    PORT = int(os.environ.get("PORT", "10000"))
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("join", join_cmd))
    app.add_handler(CommandHandler("help", lambda u,c: u.message.reply_text("Send confession with 'I...'")))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print(f"Starting webhook on port {PORT}")
    app.run_webhook(listen="0.0.0.0", port=PORT, url_path="webhook", webhook_url=f"{WEBHOOK_URL}/webhook")

if __name__ == "__main__":
    main()