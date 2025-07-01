import os
import sys
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import InvalidToken
from flask import Flask, request
from PyPDF2 import PdfReader, PdfWriter
from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from ebooklib import epub
import uuid

# בדיקת גרסת Python
if sys.version_info >= (3, 13):
    print("Running on Python 3.13 or higher, using python-telegram-bot>=20.8")

# הגדרת Flask
app = Flask(__name__)

# קריאת משתני סביבה
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise ValueError("שגיאה: משתנה הסביבה TOKEN לא הוגדר. ודא שהגדרת אותו ב-Render.")

WEBHOOK_URL = os.getenv("WEBHOOK_URL")
if not WEBHOOK_URL:
    raise ValueError("שגיאה: משתנה הסביבה WEBHOOK_URL לא הוגדר. ודא שהגדרת אותו ב-Render.")

# מיקום התמונה הקבועה בריפוזיטורי
COVER_IMAGE_PATH = "cover.jpg"  # התמונה תהיה בתיקיית הפרויקט

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "היי! אני בוט שמוסיף עמוד ראשון עם תמונה לקבצי PDF או EPUB. "
        "פשוט שלח לי קובץ, ואני אטפל בו! 😊"
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    document = update.message.document
    if document.mime_type not in ["application/pdf", "application/epub+zip"]:
        await update.message.reply_text("אנא שלח קובץ PDF או EPUB בלבד. 😊")
        return

    file = await document.get_file()
    file_extension = ".pdf" if document.mime_type == "application/pdf" else ".epub"
    file_name = f"temp_{uuid.uuid4()}{file_extension}"
    
    # הורדת הקובץ
    try:
        await file.download_to_drive(file_name)
    except Exception as e:
        await update.message.reply_text("מצטער, הייתה בעיה בהורדת הקובץ. נסה שוב! 😔")
        return
    
    # עיבוד הקובץ
    await update.message.reply_text("מעבד את הקובץ, רגע בבקשה... 😊")
    try:
        output_file = process_file(file_name, file_extension)
    except Exception as e:
        await update.message.reply_text(f"אופס, משהו השתבש בעיבוד הקובץ: {str(e)}. בדוק שהקובץ תקין ונסה שוב! 😅")
        if os.path.exists(file_name):
            os.remove(file_name)
        return
    
    # שליחת הקובץ המשודרג
    try:
        with open(output_file, "rb") as f:
            await update.message.reply_document(f, filename=f"modified_{document.file_name}")
            await update.message.reply_text("הקובץ מוכן! הנה הוא עם העמוד הראשון החדש. 🎉")
    except Exception as e:
        await update.message.reply_text("מצטער, לא הצלחתי לשלוח את הקובץ. נסה שוב מאוחר יותר! 😔")
    
    # ניקוי קבצים זמניים
    if os.path.exists(file_name):
        os.remove(file_name)
    if os.path.exists(output_file):
        os.remove(output_file)

def process_file(input_file: str, extension: str) -> str:
    output_file = f"output_{uuid.uuid4()}{extension}"
    
    # בדיקת תקינות התמונה הקבועה עם Pillow
    try:
        with Image.open(COVER_IMAGE_PATH) as img:
            img.verify()  # בדיקת תקינות התמונה
            img = Image.open(COVER_IMAGE_PATH)  # פתיחה מחדש כי verify() סוגר את הקובץ
            img_format = img.format.lower() if img.format else None
            if img_format not in ['jpeg', 'png']:
                raise ValueError("התמונה הקבועה חייבת להיות בפורמט JPEG או PNG")
    except Exception as e:
        raise Exception(f"שגיאה בתמונה הקבועה: {str(e)}")
    
    if extension == ".pdf":
        # טיפול ב-PDF
        pdf_writer = PdfWriter()
        
        # יצירת עמוד PDF עם התמונה באמצעות reportlab
        cover_pdf = "cover.pdf"
        try:
            c = canvas.Canvas(cover_pdf, pagesize=letter)
            c.drawImage(COVER_IMAGE_PATH, 0, 0, width=letter[0], height=letter[1], preserveAspectRatio=True)
            c.showPage()
            c.save()
        except Exception as e:
            raise Exception(f"שגיאה ביצירת עמוד התמונה: {str(e)}")
        
        # הוספת עמוד התמונה
        try:
            cover_reader = PdfReader(cover_pdf)
            pdf_writer.add_page(cover_reader.pages[0])
        except Exception as e:
            if os.path.exists(cover_pdf):
                os.remove(cover_pdf)
            raise Exception(f"שגיאה בקריאת עמוד התמונה: {str(e)}")
        
        # הוספת שאר עמודי הקובץ המקורי
        try:
            original_reader = PdfReader(input_file)
            for page in original_reader.pages:
                pdf_writer.add_page(page)
        except Exception as e:
            if os.path.exists(cover_pdf):
                os.remove(cover_pdf)
            raise Exception(f"שגיאה בקריאת קובץ PDF: {str(e)}")
        
        # שמירת הקובץ החדש
        with open(output_file, "wb") as f:
            pdf_writer.write(f)
        
        if os.path.exists(cover_pdf):
            os.remove(cover_pdf)
    
    elif extension == ".epub":
        # טיפול ב-EPUB
        try:
            book = epub.read_epub(input_file)
            cover_item = epub.EpubItem(
                uid="cover",
                file_name="cover.xhtml",
                media_type="application/xhtml+xml",
                content=f"""
                <html xmlns="http://www.w3.org/1999/xhtml">
                <head><title>Cover</title></head>
                <body><img src="{COVER_IMAGE_PATH}" style="width:100%;height:auto;"/></body>
                </html>
                """.encode()
            )
            book.add_item(cover_item)
            book.spine.insert(0, cover_item)  # הוספת העמוד הראשון
            epub.write_epub(output_file, book)
        except Exception as e:
            raise Exception(f"שגיאה בעיבוד קובץ EPUB: {str(e)}")
    
    return output_file

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "אני מקבל רק קבצי PDF או EPUB. שלח לי קובץ, ואוסיף לו עמוד ראשון! 😊 "
        "אם אתה צריך עזרה, כתוב /start."
    )

# הגדרת Webhook עבור Flask
@app.route(f"/{TOKEN}", methods=["POST"])
async def webhook():
    try:
        update = Update.de_json(request.get_json(force=True), application.bot)
        await application.process_update(update)
        return "OK"
    except Exception as e:
        print(f"Webhook error: {e}")
        return "Error", 500

# נקודת כניסה ראשית
if __name__ == "__main__":
    # הגדרת Application עבור python-telegram-bot v20
    application = Application.builder().token(TOKEN).build()
    
    # הוספת handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # בדיקת תקינות הטוקן והגדרת Webhook
    async def verify_and_set_webhook():
        try:
            bot_info = await application.bot.get_me()
            print(f"Bot connected successfully: {bot_info.username}")
            await application.bot.set_webhook(f"{WEBHOOK_URL}/{TOKEN}")
            print(f"Webhook set to {WEBHOOK_URL}/{TOKEN}")
        except InvalidToken:
            print("שגיאה: הטוקן אינו תקין. ודא שהזנת את הטוקן נכון ב-Render.")
            raise ValueError("שגיאה: הטוקן אינו תקין. בדוק את משתנה הסביבה TOKEN ב-Render.")
        except Exception as e:
            print(f"שגיאה בהגדרת Webhook: {e}")
            raise ValueError(f"שגיאה בהגדרת Webhook: {str(e)}")
    
    # הרצת Flask עם Webhook
    loop = asyncio.new_event_loop()  # תיקון לאזהרת DeprecationWarning
    asyncio.set_event_loop(loop)
    loop.run_until_complete(verify_and_set_webhook())
    
    port = int(os.environ.get("PORT", 8443))
    app.run(host="0.0.0.0", port=port)