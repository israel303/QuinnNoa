import os
import sys
import asyncio
import logging
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
import threading

# הגדרת לוגים
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# בדיקת גרסת Python
if sys.version_info >= (3, 13):
    logger.info("Running on Python 3.13 or higher, using python-telegram-bot>=20.8")

# הגדרת Flask
app = Flask(__name__)

# משתנה גלובלי עבור Application
application = None

# קריאת משתני סביבה
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    logger.error("Environment variable TOKEN not set")
    raise ValueError("שגיאה: משתנה הסביבה TOKEN לא הוגדר. ודא שהגדרת אותו ב-Render.")

WEBHOOK_URL = os.getenv("WEBHOOK_URL")
if not WEBHOOK_URL:
    logger.error("Environment variable WEBHOOK_URL not set")
    raise ValueError("שגיאה: משתנה הסביבה WEBHOOK_URL לא הוגדר. ודא שהגדרת אותו ב-Render.")

# מיקום התמונה הקבועה בריפוזיטורי
COVER_IMAGE_PATH = "cover.jpg"  # התמונה תהיה בתיקיית הפרויקט

# בדיקת קיום התמונה בתחילת הריצה
if not os.path.exists(COVER_IMAGE_PATH):
    logger.error(f"Cover image not found at {COVER_IMAGE_PATH}")
    raise FileNotFoundError(f"שגיאה: התמונה {COVER_IMAGE_PATH} לא נמצאה בתיקיית הפרויקט.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Received /start command")
    await update.message.reply_text(
        "היי! אני בוט שמוסיף עמוד ראשון עם תמונה לקבצי PDF או EPUB. "
        "פשוט שלח לי קובץ, ואני אטפל בו! 😊"
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info(f"Received document: {update.message.document.file_name}")
    document = update.message.document
    if document.mime_type not in ["application/pdf", "application/epub+zip"]:
        logger.warning(f"Invalid file type: {document.mime_type}")
        await update.message.reply_text("אנא שלח קובץ PDF או EPUB בלבד. 😊")
        return

    file = await document.get_file()
    file_extension = ".pdf" if document.mime_type == "application/pdf" else ".epub"
    file_name = f"temp_{uuid.uuid4()}{file_extension}"
    
    # הורדת הקובץ
    try:
        await file.download_to_drive(file_name)
        logger.info(f"File downloaded: {file_name}")
    except Exception as e:
        logger.error(f"Error downloading file: {str(e)}")
        await update.message.reply_text("מצטער, הייתה בעיה בהורדת הקובץ. נסה שוב! 😔")
        return
    
    # עיבוד הקובץ
    await update.message.reply_text("מעבד את הקובץ, רגע בבקשה... 😊")
    try:
        output_file = process_file(file_name, file_extension)
        logger.info(f"File processed: {output_file}")
    except Exception as e:
        logger.error(f"Error processing file: {str(e)}")
        await update.message.reply_text(f"אופס, משהו השתבש בעיבוד הקובץ: {str(e)}. בדוק שהקובץ תקין ונסה שוב! 😅")
        if os.path.exists(file_name):
            os.remove(file_name)
        return
    
    # שליחת הקובץ המשודרג
    try:
        with open(output_file, "rb") as f:
            await update.message.reply_document(f, filename=f"modified_{document.file_name}")
            await update.message.reply_text("הקובץ מוכן! הנה הוא עם העמוד הראשון החדש. 🎉")
        logger.info(f"File sent: {output_file}")
    except Exception as e:
        logger.error(f"Error sending file: {str(e)}")
        await update.message.reply_text("מצטער, לא הצלחתי לשלוח את הקובץ. נסה שוב מאוחר יותר! 😔")
    
    # ניקוי קבצים זמניים
    if os.path.exists(file_name):
        os.remove(file_name)
        logger.info(f"Temporary file removed: {file_name}")
    if os.path.exists(output_file):
        os.remove(output_file)
        logger.info(f"Output file removed: {output_file}")

def process_file(input_file: str, extension: str) -> str:
    output_file = f"output_{uuid.uuid4()}{extension}"
    logger.info(f"Processing file: {input_file} to {output_file}")
    
    # בדיקת תקינות התמונה הקבועה עם Pillow
    try:
        with Image.open(COVER_IMAGE_PATH) as img:
            img.verify()  # בדיקת תקינות התמונה
        # פתיחה מחדש כי verify() סוגר את הקובץ
        with Image.open(COVER_IMAGE_PATH) as img:
            img_format = img.format.lower() if img.format else None
            if img_format not in ['jpeg', 'png']:
                raise ValueError("התמונה הקבועה חייבת להיות בפורמט JPEG או PNG")
        logger.info(f"Cover image verified: {COVER_IMAGE_PATH}")
    except Exception as e:
        logger.error(f"Error with cover image: {str(e)}")
        raise Exception(f"שגיאה בתמונה הקבועה: {str(e)}")
    
    if extension == ".pdf":
        # טיפול ב-PDF
        pdf_writer = PdfWriter()
        
        # יצירת עמוד PDF עם התמונה באמצעות reportlab
        cover_pdf = f"cover_{uuid.uuid4()}.pdf"
        try:
            c = canvas.Canvas(cover_pdf, pagesize=letter)
            c.drawImage(COVER_IMAGE_PATH, 0, 0, width=letter[0], height=letter[1], preserveAspectRatio=True)
            c.showPage()
            c.save()
            logger.info(f"Cover PDF created: {cover_pdf}")
        except Exception as e:
            logger.error(f"Error creating cover PDF: {str(e)}")
            raise Exception(f"שגיאה ביצירת עמוד התמונה: {str(e)}")
        
        # הוספת עמוד התמונה
        try:
            cover_reader = PdfReader(cover_pdf)
            pdf_writer.add_page(cover_reader.pages[0])
            logger.info("Cover page added to PDF")
        except Exception as e:
            if os.path.exists(cover_pdf):
                os.remove(cover_pdf)
            logger.error(f"Error reading cover PDF: {str(e)}")
            raise Exception(f"שגיאה בקריאת עמוד התמונה: {str(e)}")
        
        # הוספת שאר עמודי הקובץ המקורי
        try:
            original_reader = PdfReader(input_file)
            for page in original_reader.pages:
                pdf_writer.add_page(page)
            logger.info("Original PDF pages added")
        except Exception as e:
            if os.path.exists(cover_pdf):
                os.remove(cover_pdf)
            logger.error(f"Error reading original PDF: {str(e)}")
            raise Exception(f"שגיאה בקריאת קובץ PDF: {str(e)}")
        
        # שמירת הקובץ החדש
        try:
            with open(output_file, "wb") as f:
                pdf_writer.write(f)
            logger.info(f"Output PDF saved: {output_file}")
        except Exception as e:
            logger.error(f"Error saving output PDF: {str(e)}")
            raise Exception(f"שגיאה בשמירת קובץ PDF: {str(e)}")
        
        if os.path.exists(cover_pdf):
            os.remove(cover_pdf)
            logger.info(f"Temporary cover PDF removed: {cover_pdf}")
    
    elif extension == ".epub":
        # טיפול ב-EPUB
        try:
            book = epub.read_epub(input_file)
            
            # הוספת התמונה לקובץ EPUB
            with open(COVER_IMAGE_PATH, 'rb') as img_file:
                img_data = img_file.read()
            
            # קביעת סוג MIME בהתאם לסוג התמונה
            img_extension = os.path.splitext(COVER_IMAGE_PATH)[1].lower()
            if img_extension == '.jpg' or img_extension == '.jpeg':
                media_type = 'image/jpeg'
            elif img_extension == '.png':
                media_type = 'image/png'
            else:
                media_type = 'image/jpeg'  # ברירת מחדל
            
            # הוספת התמונה לקובץ EPUB
            img_item = epub.EpubItem(
                uid="cover_image",
                file_name="cover_image" + img_extension,
                media_type=media_type,
                content=img_data
            )
            book.add_item(img_item)
            
            # יצירת עמוד HTML עבור התמונה
            cover_item = epub.EpubHtml(
                uid="cover",
                file_name="cover.xhtml",
                title="Cover"
            )
            cover_item.content = f"""<?xml version="1.0" encoding="utf-8"?>
            <html xmlns="http://www.w3.org/1999/xhtml">
            <head><title>Cover</title></head>
            <body style="text-align: center; margin: 0; padding: 0;">
                <img src="cover_image{img_extension}" style="width:100%; height:auto; max-width:100%; max-height:100%;"/>
            </body>
            </html>"""
            
            book.add_item(cover_item)
            book.spine.insert(0, cover_item)  # הוספת העמוד הראשון
            
            # עדכון TOC אם קיים
            if hasattr(book, 'toc') and book.toc:
                book.toc.insert(0, cover_item)
            
            epub.write_epub(output_file, book)
            logger.info(f"Output EPUB saved: {output_file}")
        except Exception as e:
            logger.error(f"Error processing EPUB: {str(e)}")
            raise Exception(f"שגיאה בעיבוד קובץ EPUB: {str(e)}")
    
    return output_file

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Received text message")
    await update.message.reply_text(
        "אני מקבל רק קבצי PDF או EPUB. שלח לי קובץ, ואוסיף לו עמוד ראשון! 😊 "
        "אם אתה צריך עזרה, כתוב /start."
    )

# הגדרת Webhook עבור Flask
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        logger.info(f"Received webhook update")
        update = Update.de_json(data, application.bot)
        if update:
            # הרצת העדכון באופן אסינכרוני
            asyncio.create_task(application.process_update(update))
            logger.info("Webhook update processed successfully")
            return "OK"
        else:
            logger.warning("Webhook received invalid update")
            return "Invalid update", 400
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        return "Error", 500

# פונקציה להרצת Flask בחוט נפרד
def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)

# נקודת כניסה ראשית
if __name__ == "__main__":
    # הגדרת Application עבור python-telegram-bot v20
    try:
        application = Application.builder().token(TOKEN).build()
    except InvalidToken:
        logger.error("Invalid token provided")
        raise ValueError("שגיאה: הטוקן אינו תקין. בדוק את משתנה הסביבה TOKEN ב-Render.")
    
    # הוספת handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # בדיקת תקינות הטוקן והגדרת Webhook
    async def setup_application():
        try:
            await application.initialize()  # איתחול ה-Application
            logger.info("Application initialized")
            bot_info = await application.bot.get_me()
            logger.info(f"Bot connected successfully: {bot_info.username}")
            await application.bot.set_webhook(f"{WEBHOOK_URL}/{TOKEN}")
            logger.info(f"Webhook set to {WEBHOOK_URL}/{TOKEN}")
        except InvalidToken:
            logger.error("Invalid token during webhook setup")
            raise ValueError("שגיאה: הטוקן אינו תקין. בדוק את משתנה הסביבה TOKEN ב-Render.")
        except Exception as e:
            logger.error(f"Error setting webhook: {str(e)}")
            raise ValueError(f"שגיאה בהגדרת Webhook: {str(e)}")
    
    # הרצת הגדרות ראשוניות
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(setup_application())
        logger.info("Application setup completed successfully")
    except Exception as e:
        logger.error(f"Failed to setup application: {str(e)}")
        loop.close()
        raise
    
    # הרצת Flask בחוט נפרד
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("Flask server started")
    
    # השארת הלולאה פעילה
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
    finally:
        loop.close()