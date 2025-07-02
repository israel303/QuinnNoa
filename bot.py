import os
import io
import asyncio
import logging
from typing import Optional
from telegram import Update, Document
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import TelegramError, BadRequest
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from PIL import Image
from ebooklib import epub
from flask import Flask, request, jsonify
import threading

# הגדרת לוגים
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class EfficientCoverBot:
    """בוט יעיל להוספת כיסוי לקבצי PDF ו-EPUB"""
    
    # הגדרת קבועים
    MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
    SUPPORTED_FORMATS = ["application/pdf", "application/epub+zip"]
    COVER_IMAGE_PATH = "cover.jpg"
    
    def __init__(self, token: str, webhook_url: str):
        self.token = token
        self.webhook_url = webhook_url
        self.app = Application.builder().token(token).build()
        self._validate_cover_image()
        self._setup_handlers()
    
    def _validate_cover_image(self) -> None:
        """בדיקת תקינות תמונת הכיסוי"""
        if not os.path.exists(self.COVER_IMAGE_PATH):
            raise FileNotFoundError(f"תמונת הכיסוי לא נמצאה: {self.COVER_IMAGE_PATH}")
        
        try:
            with Image.open(self.COVER_IMAGE_PATH) as img:
                img.verify()
            logger.info(f"תמונת כיסוי תקינה: {self.COVER_IMAGE_PATH}")
        except Exception as e:
            raise ValueError(f"תמונת הכיסוי אינה תקינה: {e}")
    
    def _setup_handlers(self) -> None:
        """הגדרת handlers לבוט"""
        self.app.add_handler(CommandHandler("start", self.start_handler))
        self.app.add_handler(CommandHandler("help", self.help_handler))
        self.app.add_handler(MessageHandler(filters.Document.ALL, self.document_handler))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.text_handler))
        
        # Error handler
        self.app.add_error_handler(self.error_handler)
    
    async def start_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """פקודת /start"""
        welcome_message = (
            "🎨 **בוט הוספת כיסוי לקבצים**\n\n"
            "אני מוסיף עמוד כיסוי עם תמונה לקבצי PDF ו-EPUB!\n\n"
            "**איך להשתמש:**\n"
            "• שלח לי קובץ PDF או EPUB\n"
            "• אקבל את הקובץ עם כיסוי חדש\n"
            "• גודל מקסימלי: 20MB\n\n"
            "לעזרה נוספת: /help"
        )
        await update.message.reply_text(welcome_message, parse_mode='Markdown')
        logger.info(f"משתמש {update.effective_user.id} התחיל את הבוט")
    
    async def help_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """פקודת /help"""
        help_message = (
            "📚 **עזרה לשימוש בבוט**\n\n"
            "**פורמטים נתמכים:**\n"
            "• PDF (.pdf)\n"
            "• EPUB (.epub)\n\n"
            "**הגבלות:**\n"
            "• גודל מקסימלי: 20MB\n"
            "• קבצים תקינים בלבד\n\n"
            "**שאלות נפוצות:**\n"
            "• הבוט מוסיף את הכיסוי כעמוד ראשון\n"
            "• התמונה מותאמת לגודל העמוד\n"
            "• הקובץ המקורי נשמר כפי שהיה\n\n"
            "צריך עזרה? פנה למפתח הבוט!"
        )
        await update.message.reply_text(help_message, parse_mode='Markdown')
    
    async def document_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """טיפול בקבצים שנשלחו"""
        document: Document = update.message.document
        user_id = update.effective_user.id
        
        logger.info(f"קובץ התקבל מהמשתמש {user_id}: {document.file_name}")
        
        # בדיקת תקינות הקובץ
        validation_error = self._validate_document(document)
        if validation_error:
            await update.message.reply_text(validation_error)
            return
        
        # הודעת התחלת עיבוד
        processing_msg = await update.message.reply_text("🔄 מעבד את הקובץ...")
        
        try:
            # הורדת הקובץ לזיכרון
            file = await document.get_file()
            file_bytes = io.BytesIO()
            await file.download_to_memory(file_bytes)
            file_bytes.seek(0)
            
            # עיבוד הקובץ
            if document.mime_type == "application/pdf":
                result_bytes = await asyncio.to_thread(self._process_pdf, file_bytes)
            else:  # EPUB
                result_bytes = await asyncio.to_thread(self._process_epub, file_bytes)
            
            # שליחת הקובץ המעובד
            result_io = io.BytesIO(result_bytes)
            result_io.name = f"cover_{document.file_name}"
            
            await update.message.reply_document(
                document=result_io,
                filename=f"cover_{document.file_name}",
                caption="✅ הקובץ מוכן עם כיסוי חדש!"
            )
            
            # מחיקת הודעת העיבוד
            await processing_msg.delete()
            
            logger.info(f"קובץ נשלח בהצלחה למשתמש {user_id}")
            
        except Exception as e:
            logger.error(f"שגיאה בעיבוד קובץ למשתמש {user_id}: {e}")
            await processing_msg.edit_text(
                f"❌ אופס! קרתה שגיאה בעיבוד הקובץ:\n`{str(e)[:100]}...`\n\nנסה שוב עם קובץ אחר.",
                parse_mode='Markdown'
            )
    
    async def text_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """טיפול בהודעות טקסט"""
        await update.message.reply_text(
            "📄 אני מעבד רק קבצי PDF ו-EPUB!\n\n"
            "שלח לי קובץ ואני אוסיף לו כיסוי יפה 🎨\n"
            "לעזרה: /help"
        )
    
    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """טיפול בשגיאות"""
        logger.error(f"שגיאה בבוט: {context.error}")
        
        if isinstance(update, Update) and update.message:
            try:
                await update.message.reply_text(
                    "❌ אופס! קרתה שגיאה לא צפויה.\nנסה שוב או פנה למפתח הבוט."
                )
            except:
                pass
    
    def _validate_document(self, document: Document) -> Optional[str]:
        """בדיקת תקינות הקובץ"""
        if document.file_size > self.MAX_FILE_SIZE:
            return f"❌ הקובץ גדול מדי! מקסימום {self.MAX_FILE_SIZE // (1024*1024)}MB"
        
        if document.mime_type not in self.SUPPORTED_FORMATS:
            return "❌ פורמט לא נתמך! שלח קובץ PDF או EPUB בלבד"
        
        if not document.file_name:
            return "❌ הקובץ חייב להיות עם שם תקין"
        
        return None
    
    def _process_pdf(self, file_bytes: io.BytesIO) -> bytes:
        """עיבוד קובץ PDF"""
        logger.info("מתחיל עיבוד PDF")
        
        try:
            cover_pdf_bytes = self._create_pdf_cover()
            original_reader = PdfReader(file_bytes)
            cover_reader = PdfReader(io.BytesIO(cover_pdf_bytes))
            
            writer = PdfWriter()
            writer.add_page(cover_reader.pages[0])
            
            for page in original_reader.pages:
                writer.add_page(page)
            
            output = io.BytesIO()
            writer.write(output)
            
            logger.info("עיבוד PDF הושלם בהצלחה")
            return output.getvalue()
            
        except Exception as e:
            logger.error(f"שגיאה בעיבוד PDF: {e}")
            raise Exception(f"שגיאה בעיבוד קובץ PDF: {str(e)}")
    
    def _process_epub(self, file_bytes: io.BytesIO) -> bytes:
        """עיבוד קובץ EPUB"""
        logger.info("מתחיל עיבוד EPUB")
        
        try:
            book = epub.read_epub(file_bytes)
            
            with open(self.COVER_IMAGE_PATH, 'rb') as img_file:
                img_data = img_file.read()
            
            img_extension = os.path.splitext(self.COVER_IMAGE_PATH)[1].lower()
            media_type = 'image/jpeg' if img_extension in ['.jpg', '.jpeg'] else 'image/png'
            
            img_item = epub.EpubItem(
                uid="cover_image",
                file_name=f"cover{img_extension}",
                media_type=media_type,
                content=img_data
            )
            book.add_item(img_item)
            
            cover_html = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
    <title>Cover</title>
    <style>
        body {{ margin: 0; padding: 0; text-align: center; }}
        img {{ max-width: 100%; max-height: 100vh; }}
    </style>
</head>
<body>
    <img src="cover{img_extension}" alt="Cover"/>
</body>
</html>"""
            
            cover_item = epub.EpubHtml(
                uid="cover_page",
                file_name="cover.xhtml",
                title="Cover"
            )
            cover_item.content = cover_html
            
            book.add_item(cover_item)
            book.spine.insert(0, cover_item)
            
            output = io.BytesIO()
            epub.write_epub(output, book)
            
            logger.info("עיבוד EPUB הושלם בהצלחה")
            return output.getvalue()
            
        except Exception as e:
            logger.error(f"שגיאה בעיבוד EPUB: {e}")
            raise Exception(f"שגיאה בעיבוד קובץ EPUB: {str(e)}")
    
    def _create_pdf_cover(self) -> bytes:
        """יצירת עמוד כיסוי PDF"""
        cover_bytes = io.BytesIO()
        c = canvas.Canvas(cover_bytes, pagesize=letter)
        
        c.drawImage(
            self.COVER_IMAGE_PATH, 
            0, 0, 
            width=letter[0], 
            height=letter[1],
            preserveAspectRatio=True,
            anchor='c'
        )
        
        c.showPage()
        c.save()
        
        return cover_bytes.getvalue()
    
    async def setup_webhook(self):
        """הגדרת webhook"""
        await self.app.initialize()
        webhook_url = f"{self.webhook_url}/webhook/{self.token}"
        
        try:
            await self.app.bot.set_webhook(webhook_url)
            logger.info(f"Webhook נקבע בהצלחה: {webhook_url}")
            
            # בדיקת מידע על הבוט
            bot_info = await self.app.bot.get_me()
            logger.info(f"בוט מחובר: @{bot_info.username}")
            
        except Exception as e:
            logger.error(f"שגיאה בהגדרת webhook: {e}")
            raise
    
    async def process_webhook_update(self, update_data: dict):
        """עיבוד עדכון מ-webhook"""
        try:
            update = Update.de_json(update_data, self.app.bot)
            if update:
                await self.app.process_update(update)
        except Exception as e:
            logger.error(f"שגיאה בעיבוד webhook update: {e}")

# יצירת Flask app לwebhook
flask_app = Flask(__name__)
bot_instance = None

@flask_app.route('/', methods=['GET'])
def health_check():
    """בדיקת תקינות השירות"""
    return jsonify({
        "status": "running",
        "service": "Telegram Cover Bot",
        "version": "1.0"
    })

@flask_app.route(f'/webhook/<token>', methods=['POST'])
def webhook_handler(token):
    """מטפל ב-webhook updates"""
    global bot_instance
    
    if not bot_instance or bot_instance.token != token:
        return jsonify({"error": "Invalid token"}), 401
    
    try:
        update_data = request.get_json(force=True)
        if not update_data:
            return jsonify({"error": "No data received"}), 400
        
        # יצירת task לעיבוד אסינכרוני
        asyncio.create_task(bot_instance.process_webhook_update(update_data))
        
        return jsonify({"status": "ok"})
        
    except Exception as e:
        logger.error(f"שגיאה ב-webhook handler: {e}")
        return jsonify({"error": str(e)}), 500

def run_flask():
    """הרצת Flask server"""
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port, debug=False)

async def main():
    """פונקציה ראשית"""
    global bot_instance
    
    # קריאת משתני סביבה
    token = os.getenv("BOT_TOKEN")
    webhook_url = os.getenv("WEBHOOK_URL")
    
    if not token:
        raise ValueError("❌ משתנה הסביבה BOT_TOKEN לא הוגדר!")
    
    if not webhook_url:
        raise ValueError("❌ משתנה הסביבה WEBHOOK_URL לא הוגדר!")
    
    # יצירת הבוט
    bot_instance = EfficientCoverBot(token, webhook_url)
    
    # הגדרת webhook
    await bot_instance.setup_webhook()
    
    # הרצת Flask בחוט נפרד
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    logger.info("🚀 הבוט רץ במצב webhook!")
    logger.info(f"🌐 URL: {webhook_url}/webhook/{token}")
    
    # השארת הבוט פעיל
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("עוצר את הבוט...")
    finally:
        await bot_instance.app.shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("הבוט נעצר על ידי המשתמש")
    except Exception as e:
        logger.error(f"שגיאה קריטית: {e}")
        raise