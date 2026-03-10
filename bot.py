"""
ClipAI Telegram Bot
Send a video → get viral Shorts back as .mp4 files
"""

import os, json, uuid, subprocess, asyncio, tempfile
from telegram import Update, Message
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode
import anthropic

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

WORK_DIR = "/tmp/clipai"
os.makedirs(WORK_DIR, exist_ok=True)

anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ─────────────────────────────────────────
# /start command
# ─────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✂️ *Welcome to ClipAI Bot!*\n\n"
        "Send me any video and I'll:\n"
        "🎯 Detect the most viral moments\n"
        "✂️ Cut them into Shorts (9:16 format)\n"
        "✍️ Write captions with emojis\n"
        "📤 Send the clips back to you\n\n"
        "Just send a video file to get started!\n\n"
        "_Supports MP4, MOV, AVI up to 2GB_",
        parse_mode=ParseMode.MARKDOWN
    )


# ─────────────────────────────────────────
# /help command
# ─────────────────────────────────────────
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *How to use ClipAI Bot:*\n\n"
        "1️⃣ Download your YouTube video\n"
        "   • Use yt-dlp, 4K Downloader, or savefrom.net\n\n"
        "2️⃣ Send the video file here\n\n"
        "3️⃣ Wait ~2-5 mins while I process it\n\n"
        "4️⃣ Receive your viral Shorts! 🎬\n\n"
        "*Commands:*\n"
        "/start — Welcome message\n"
        "/help — This message\n"
        "/status — Check if bot is online",
        parse_mode=ParseMode.MARKDOWN
    )


# ─────────────────────────────────────────
# /status command
# ─────────────────────────────────────────
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ ClipAI Bot is online and ready!")


# ─────────────────────────────────────────
# Handle video uploads
# ─────────────────────────────────────────
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user = message.from_user.first_name

    # Get file object (video or document)
    file_obj = message.video or message.document
    if not file_obj:
        await message.reply_text("❌ Please send a video file (.mp4, .mov, etc.)")
        return

    # Check file size (2GB Telegram limit)
    if file_obj.file_size and file_obj.file_size > 2_000_000_000:
        await message.reply_text("❌ File too large! Max 2GB please.")
        return

    job_id = str(uuid.uuid4())[:8]
    job_dir = os.path.join(WORK_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    status_msg = await message.reply_text(
        "⏳ *Got your video!* Starting analysis…\n\n"
        "```\n"
        "[ ] Downloading from Telegram\n"
        "[ ] AI detecting viral moments\n"
        "[ ] Cutting clips\n"
        "[ ] Sending back to you\n"
        "```",
        parse_mode=ParseMode.MARKDOWN
    )

    try:
        # ── Step 1: Download from Telegram ──
        await _edit_status(status_msg,
            "⬇️ *Downloading your video…*\n\n"
            "```\n"
            "[✓] Receiving from Telegram\n"
            "[ ] AI detecting viral moments\n"
            "[ ] Cutting clips\n"
            "[ ] Sending back to you\n"
            "```"
        )

        tg_file = await context.bot.get_file(file_obj.file_id)
        video_path = os.path.join(job_dir, "input.mp4")
        await tg_file.download_to_drive(video_path)

        # ── Step 2: Get video duration ──
        duration = _get_duration(video_path)
        duration_str = f"{int(duration//60)}m {int(duration%60)}s" if duration else "unknown"

        # ── Step 3: Ask Claude for viral clips ──
        await _edit_status(status_msg,
            "🤖 *AI analyzing viral moments…*\n\n"
            "```\n"
            "[✓] Video received\n"
            "[✓] AI detecting viral moments\n"
            "[ ] Cutting clips\n"
            "[ ] Sending back to you\n"
            "```"
        )

        clips = await asyncio.get_event_loop().run_in_executor(
            None, _analyze_with_claude, duration, duration_str
        )

        if not clips:
            await status_msg.edit_text("❌ Could not detect clips. Try a different video.")
            return

        # ── Step 4: Cut clips with ffmpeg ──
        await _edit_status(status_msg,
            f"✂️ *Cutting {len(clips)} viral clips…*\n\n"
            "```\n"
            "[✓] Video received\n"
            "[✓] AI found viral moments\n"
            "[✓] Cutting clips\n"
            "[ ] Sending back to you\n"
            "```"
        )

        cut_clips = await asyncio.get_event_loop().run_in_executor(
            None, _cut_clips, video_path, clips, job_dir
        )

        # ── Step 5: Send clips back ──
        await _edit_status(status_msg,
            "📤 *Sending your Shorts…*\n\n"
            "```\n"
            "[✓] Video received\n"
            "[✓] AI found viral moments\n"
            "[✓] Clips cut\n"
            "[✓] Sending back to you\n"
            "```"
        )

        sent_count = 0
        for clip in cut_clips:
            if not clip.get("ready"):
                continue
            try:
                caption = (
                    f"{'🔥 TOP PICK — ' if clip.get('topPick') else ''}"
                    f"{clip['emoji']} *{clip['title']}*\n\n"
                    f"⏱ `{clip['start']} → {clip['end']}`\n"
                    f"📊 Viral Score: *{clip['viralScore']}%*\n\n"
                    f"{clip['caption']}"
                )
                # Telegram caption max 1024 chars
                if len(caption) > 1024:
                    caption = caption[:1020] + "…"

                with open(clip["output_path"], "rb") as f:
                    await context.bot.send_video(
                        chat_id=message.chat_id,
                        video=f,
                        caption=caption,
                        parse_mode=ParseMode.MARKDOWN,
                        supports_streaming=True
                    )
                sent_count += 1
                await asyncio.sleep(1)  # avoid flood limits

            except Exception as e:
                print(f"Failed to send clip {clip['id']}: {e}")

        # Final summary
        await status_msg.edit_text(
            f"✅ *Done! Sent {sent_count}/{len(cut_clips)} clips*\n\n"
            f"🎬 Your viral Shorts are ready to post!\n"
            f"📋 Each clip has its caption — just copy & paste when posting.\n\n"
            f"_Send another video anytime!_",
            parse_mode=ParseMode.MARKDOWN
        )

    except Exception as e:
        await status_msg.edit_text(
            f"❌ *Something went wrong:*\n`{str(e)[:200]}`\n\nPlease try again.",
            parse_mode=ParseMode.MARKDOWN
        )

    finally:
        # Cleanup
        try:
            import shutil
            shutil.rmtree(job_dir, ignore_errors=True)
        except:
            pass


# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

async def _edit_status(msg: Message, text: str):
    try:
        await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)
    except:
        pass


def _get_duration(video_path: str) -> float:
    """Get video duration using ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", video_path],
            capture_output=True, text=True
        )
        info = json.loads(result.stdout)
        return float(info["format"]["duration"])
    except:
        return 0


def _analyze_with_claude(duration: float, duration_str: str) -> list:
    """Ask Claude to identify viral clip timestamps."""
    prompt = f"""A video is {duration_str} long ({int(duration)} seconds total).

Identify 4-5 viral clip moments spread throughout the video.
Space clips across the full duration — don't cluster them at the start.

Return ONLY a raw JSON array:
[{{"id":1,"topPick":true,"emoji":"🔥","title":"CLIP TITLE IN CAPS","start":"00:01:30","end":"00:02:15","vibe":"Comedy","viralScore":96,"hook":"One sentence why this is viral","caption":"Full caption with emojis ready to post\\n\\n#hashtag1 #hashtag2 #hashtag3","filename":"clip1_name.mp4"}}]

Rules:
- topPick=true for top 2 clips only
- Each clip must be 30-90 seconds long
- Spread clips evenly across the {duration_str} video
- Return raw JSON only, no markdown"""

    message = anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


def _cut_clips(video_path: str, clips: list, job_dir: str) -> list:
    """Cut each clip using ffmpeg and convert to 9:16 vertical."""
    results = []

    for clip in clips:
        out_path = os.path.join(job_dir, clip["filename"])

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-ss", clip["start"],
            "-to", clip["end"],
            "-c:v", "libx264",
            "-c:a", "aac",
            "-preset", "fast",
            "-crf", "23",
            # Crop to 9:16 vertical for Shorts
            "-vf", "crop=ih*9/16:ih,scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
            "-movflags", "+faststart",
            out_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        results.append({
            **clip,
            "output_path": out_path,
            "ready": result.returncode == 0 and os.path.exists(out_path)
        })

    return results


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
def main():
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN not set!")
        return
    if not ANTHROPIC_API_KEY:
        print("❌ ANTHROPIC_API_KEY not set!")
        return

    print("🤖 ClipAI Bot starting...")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status))

    # Handle video files and documents
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))

    print("✅ Bot is running!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
        
