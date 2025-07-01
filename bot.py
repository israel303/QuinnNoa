import os
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from flask import Flask, request
from PyPDF2 import PdfReader, PdfWriter
from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from ebooklib import epub
import io
import uuid

# הגדרת Flask
app = Flask(__name__)

# הגדרות טלגרם
TOKEN = "YOUR_BOT_TOKEN"  # החלף בטוקן של הבוט שלך
WEBHOOK_URL = "YOUR_RENDER_URL"  # החלף בכתובת ה-Web Service שלך ב-Render

# מיקום התמונה הקבועה בריפוזיטורי
COVER_IMAGE_PATH = "cover.jpg"  # התמונה תהיה בתיקיית הפרויקט

def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(
        "היי! אני בוט שמוסיף עמוד ראשון עם תמונה לקבצי PDF או EPUB. "
        "פשוט שלח לי קובץ, ואני אטפל בו! 😊"
    )

def handle_document(update: Update, context: CallbackContext) -> None:
    document = update.message.document
    if document.mime_type in ["application/pdf", "application/epub+zip"]:
        file = context.bot.get_file(document.file_id)
        file_extension = ".pdf" if document.mime_type == "application/pdf" else ".epub"
        file_name = f"temp_{uuid.uuid4()}{file_extension}"
        
        # הורדת הקובץ
        try:
            file.download(file_name)
        except Exception as e:
            update.message.reply_text("מצטער, הייתה בעיה בהורדת הקובץ. נסה שוב! 😔")
            return
        
        # עיבוד הקובץ
        update.message.reply_text("מעבד את הקובץ, רגע בבקשה... 😊")
        try:
            output_file = process_file(file_name, file_extension)
        except Exception as e:
            update.message.reply_text("אופס, משהו השתבש בעיבוד הקובץ. בדוק שהקובץ תקין ונסה שוב! 😅")
            os.remove(file_name)
            return
        
        # שליחת הקובץ המשודרג
        try:
            with open(output_file, "rb") as f:
                update.message.reply_document(f, filename=f"modified_{document.file_name}")
                update.message.reply_text("הקובץ מוכן! הנה הוא עם העמוד הראשון החדש. 🎉")
        except Exception as e:
            update.message.reply_text("מצטער, לא הצלחתי לשלוח את הקובץ. נסה שוב מאוחר יותר! 😔")
        
        # ניקוי קבצים זמניים
        os.remove(file_name)
        os.remove(output_file)
    else:
        update.message.reply_text("אנא שלח קובץ PDF או EPUB בלבד. 😊")

def process_file(input_file: str, extension: str) -> str:
    output_file = f"output_{uuid.uuid4()}{extension}"
    
    if extension == ".pdf":
        # טיפול ב-PDF
        pdf_writer = PdfWriter()
        
        # יצירת עמוד PDF עם התמונה באמצעות reportlab
        cover_pdf = "cover.pdf"
        try:
            c = canvas.Canvas(cover_pdf, pagesize=letter)
            img = Image.open(COVER_IMAGE_PATH)
            img_width, img_height = img.size
            # התאמת התמונה לגודל העמוד
            c.drawImage(COVER_IMAGE_PATH, 0, 0, width=letter[0], height=letter[1], preserveAspectRatio=True)
            c.showPage()
            c.save()
        except Exception as e:
            raise Exception("שגיאה ביצירת עמוד התמונה")
        
        # הוספת עמוד התמונה
        cover_reader = PdfReader(cover_pdf)
        pdf_writer.add_page(cover_reader.pages[0])
        
        # הוספת שאר עמודי הקובץ המקורי
        original_reader = PdfReader(input_file)
        for page in original_reader.pages:
            pdf_writer.add_page(page)
        
        # שמירת הקובץ החדש
        with open(output_file, "wb") as f:
            pdf_writer.write(f)
        
        os.remove(cover_pdf)
    
    elif extension == ".epub":
        # טיפול ב-EPUB
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
    
    return output_file

# טיפול בהודעות טקסט שאינן קבצים
def handle_text(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(
        "אני מקבל רק קבצי PDF או EPUB. שלח לי קובץ, ואוסיף לו עמוד ראשון! 😊 "
        "אם אתה צריך עזרה, כתוב /start."
    )

# הגדרת Webhook עבור Render
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "OK"

# נקודת כניסה ראשית
if __name__ == "__main__":
    updater = Updater(TOKEN, use_context=True)
    dispatcher = updater.dispatcher
    
    # הוספת handlers
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(MessageHandler(Filters.document, handle_document))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text))
    
    # הגדרת Webhook
    updater.bot.set_webhook(f"{WEBHOOK_URL}/{TOKEN}")
    
    # הרצת Flask
    port = int(os.environ.get("PORT", 8443))
    app.run(host="0.0.0.0", port=port)