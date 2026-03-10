import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✂️ Welcome to ClipSnap Bot!\n\n"
        "Send me a video file and I will cut it into viral Shorts!\n\n"
        "Just send any video to get started."
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me a video file to get started!")

def main():
    if not TELEGRAM_TOKEN:
        print("TELEGRAM_TOKEN not set!")
        return
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    print("Bot started!")
    app.run_polling()

if __name__ == "__main__":
    main()
