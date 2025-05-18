from telethon import TelegramClient, events
import asyncio
import os
import base64
from dotenv import load_dotenv
from flask import Flask, send_file, jsonify
import threading
from telegram import Bot
from telegram.error import TelegramError
import schedule
import time
from github import Github
from binance.client import Client as BinanceClient # <-- مكتبة Binance الجديدة

# تحميل متغيرات البيئة من ملف .env
load_dotenv()

# بيانات API من متغيرات البيئة
api_id = os.getenv('API_ID')
api_hash = os.getenv('API_HASH')
phone_number = os.getenv('PHONE_NUMBER')

# توكن البوت الخاص بك
telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
chat_id = os.getenv('CHAT_ID')  # معرف الدردشة الخاص بك

# تحويل النص Base64 إلى ملف
session_data = os.getenv('SESSION_FILE')
if session_data:
    with open("session_name.session", "wb") as file:
        file.write(base64.b64decode(session_data))

# إنشاء عميل تلغرام
client = TelegramClient('session_name', api_id, api_hash)

# ملفات المشروع
# input_file = "crypto_pairs.txt" # لم نعد بحاجة إلى هذا الملف
output_file = "halal_crypto.txt"  # ملف لحفظ الرموز الحلال

# اسم البوت الذي تتفاعل معه
bot_username = 'CryptoGulfHalal_Bot'  # استبدلها باسم البوت

# إنشاء تطبيق Flask
app = Flask(__name__)

# قائمة لتخزين العملات التي تم فحصها
checked_cryptos = set()

# قائمة لتخزين العملات الحلال
halal_cryptos = set()

# متغير لتتبع حالة الفحص
is_checking_complete = False

# إنشاء بوت Telegram للإشعارات
telegram_bot = Bot(token=telegram_bot_token)

# بيانات GitHub
github_token = os.getenv('GITHUB_TOKEN')
repo_name = os.getenv('REPO_NAME')
file_path = "pairs.txt" # اسم الملف الذي سيتم تحديثه على GitHub

# إنشاء عميل GitHub
github_client = Github(github_token)
repo = None # سيتم تهيئته لاحقًا بعد التأكد من repo_name
if github_token and repo_name:
    try:
        repo = github_client.get_repo(repo_name)
    except Exception as e:
        print(f"خطأ في تهيئة مستودع GitHub: {e}. تأكد من صحة GITHUB_TOKEN و REPO_NAME.")
else:
    print("تحذير: لم يتم تكوين GITHUB_TOKEN أو REPO_NAME. لن يتم تحديث GitHub.")


async def test_bot_connection():
    """
    دالة لاختبار إرسال رسالة إلى البوت.
    """
    if not chat_id or not telegram_bot_token:
        print("تحذير: لم يتم تكوين TELEGRAM_BOT_TOKEN أو CHAT_ID. لا يمكن إرسال رسالة اختبار.")
        return
    try:
        await telegram_bot.send_message(chat_id=chat_id, text="بدء عملية فحص العملات من Binance لتحديد المطابقة الشرعية #حلال")
        print("تم إرسال رسالة بدء الفحص إلى بوت الإشعارات بنجاح.")
    except TelegramError as e:
        print(f"حدث خطأ أثناء إرسال رسالة الاختبار: {e}")

async def send_halal_crypto_notification(crypto_pair_details):
    """
    دالة لإرسال إشعار بعملة حلال واحدة إلى بوت Telegram.
    """
    if not chat_id or not telegram_bot_token:
        return # لا يمكن الإرسال بدون إعدادات البوت
    try:
        message_text = (
            f"✅ عملة جديدة مطابقة للشروط الشرعية:\n"
            f"العملة: {crypto_pair_details.get('name', 'غير متوفر')}\n"
            f"الحكم: {crypto_pair_details.get('ruling', 'غير متوفر')}\n"
            f"الرابط: {crypto_pair_details.get('link', 'غير متوفر')}\n"
            f"المصدر: {crypto_pair_details.get('source', 'غير متوفر')}\n"
            f"تحذير: {crypto_pair_details.get('warning', 'لا يوجد')}"
        )
        await telegram_bot.send_message(chat_id=chat_id, text=message_text)
        print(f"تم إرسال إشعار بالعملة الحلال: {crypto_pair_details.get('name')}")
    except TelegramError as e:
        print(f"حدث خطأ أثناء إرسال إشعار العملة الحلال إلى البوت: {e}")

async def check_crypto(crypto_symbol_without_usdt):
    """
    دالة لفحص عملة واحدة وإرجاع النتيجة.
    crypto_symbol_without_usdt: رمز العملة بدون USDT (مثال: BTC)
    """
    try:
        print(f"إرسال طلب فحص العملة: {crypto_symbol_without_usdt} إلى {bot_username}")
        await client.send_message(bot_username, f"حكم {crypto_symbol_without_usdt}")
    except Exception as e:
        print(f"حدث خطأ أثناء إرسال الطلب لفحص {crypto_symbol_without_usdt}: {e}")
        return None

    response_received_event = asyncio.Event()
    result_data = None

    @client.on(events.NewMessage(from_users=bot_username, incoming=True))
    async def handler(event):
        nonlocal result_data
        message_text = event.message.message
        print(f"تم استلام الرد من {bot_username}: {message_text[:100]}...") # طباعة جزء من الرسالة

        # التحقق مما إذا كان الرد خاص بالعملة المطلوبة
        # قد تحتاج لتحسين هذا الجزء لضمان أن الرد هو للعملة الصحيحة إذا كان البوت يرد بسرعة على عدة طلبات
        if crypto_symbol_without_usdt.lower() in message_text.lower() or "أسم العملة:" in message_text :
            try:
                if "✅" in message_text:
                    name = message_text.split("أسم العملة:")[1].split("\n")[0].strip()
                    ruling = message_text.split("حكم العملة:")[1].split("\n")[0].strip()
                    link = message_text.split("رابط الحكم:")[1].split("\n")[0].strip()
                    source = message_text.split("مصدر الحكم:")[1].split("\n")[0].strip()
                    warning_section = message_text.split("تحذير:")
                    warning = warning_section[1].strip() if len(warning_section) > 1 else "لا يوجد"

                    result_data = {
                        "name": name, # اسم العملة كما ورد من البوت
                        "original_symbol_checked": crypto_symbol_without_usdt, # الرمز الذي تم فحصه
                        "ruling": ruling,
                        "link": link,
                        "source": source,
                        "warning": warning
                    }
                    print(f"العملة {name} ({crypto_symbol_without_usdt}) -> حلال/مباح (تحتوي على ✅)")
                else:
                    print(f"العملة {crypto_symbol_without_usdt} -> غير حلال/مباح (لا تحتوي على ✅ في الرد)")
                    result_data = None # تعيين صريح لـ None
            except Exception as e:
                print(f"حدث خطأ أثناء تحليل الرسالة للعملة {crypto_symbol_without_usdt}: {e}")
                print(f"الرسالة الكاملة التي سببت الخطأ: {message_text}")
                result_data = None # تعيين صريح لـ None
            finally:
                response_received_event.set() # الإشارة إلى استلام الرد ومعالجته
        else:
            # هذا الرد قد يكون لعملة أخرى أو رسالة عامة من البوت
            print(f"تم استلام رسالة من {bot_username} لا تتعلق مباشرة بـ {crypto_symbol_without_usdt} أو لا تحتوي على 'أسم العملة:'. تجاهل...")


    try:
        # الانتظار لمدة معقولة للرد (مثلاً 60 ثانية)
        await asyncio.wait_for(response_received_event.wait(), timeout=60.0)
    except asyncio.TimeoutError:
        print(f"انتهت مهلة انتظار الرد من البوت للعملة: {crypto_symbol_without_usdt}")
        result_data = None # تعيين صريح لـ None
    finally:
        client.remove_event_handler(handler) # إزالة المعالج بعد الانتهاء أو المهلة

    return result_data


async def get_binance_usdt_pairs():
    """
    دالة لجلب جميع أزواج USDT من Binance.
    """
    try:
        print("جاري جلب أزواج العملات من Binance...")
        # لا حاجة لمفاتيح API لجلب معلومات السوق العامة
        binance_client = BinanceClient()
        exchange_info = await asyncio.to_thread(binance_client.get_exchange_info) # تشغيل الاستدعاء المتزامن في خيط منفصل
        
        usdt_pairs = []
        if 'symbols' in exchange_info:
            for symbol_info in exchange_info['symbols']:
                # التحقق من أن حالة التداول طبيعية وأن الزوج ينتهي بـ USDT
                if symbol_info['symbol'].endswith('USDT') and symbol_info['status'] == 'TRADING':
                    usdt_pairs.append(symbol_info['symbol'])
            print(f"تم جلب {len(usdt_pairs)} زوج عملات USDT قيد التداول من Binance.")
        else:
            print("لم يتم العثور على مفتاح 'symbols' في استجابة Binance API.")
        
        if not usdt_pairs:
            print("لم يتم العثور على أزواج USDT على Binance أو حدث خطأ.")
        return usdt_pairs
            
    except Exception as e:
        print(f"حدث خطأ أثناء جلب أزواج العملات من Binance: {e}")
        return []

async def check_all_cryptos():
    """
    دالة لفحص جميع العملات من Binance.
    """
    global is_checking_complete, halal_cryptos, checked_cryptos
    
    # إعادة تعيين القوائم عند كل فحص جديد لضمان عدم تراكم البيانات من فحوصات سابقة إذا كان السكريبت يعمل لفترة طويلة
    halal_cryptos = set()
    # checked_cryptos يمكن الإبقاء عليها لتجنب إعادة فحص نفس العملات عبر جلسات تشغيل مختلفة إذا كان هذا هو المطلوب
    # أو إعادة تعيينها إذا أردت فحص كل شيء من جديد في كل مرة يتم استدعاء الدالة
    # checked_cryptos = set() # قم بإلغاء التعليق إذا كنت تريد إعادة فحص كل شيء في كل مرة

    if not api_id or not api_hash or not phone_number:
        print("خطأ: لم يتم تكوين بيانات اعتماد Telegram (API_ID, API_HASH, PHONE_NUMBER). لا يمكن بدء الفحص.")
        is_checking_complete = True
        return

    try:
        if not client.is_connected():
            await client.connect()
        if not await client.is_user_authorized():
            print("العميل غير مصرح له. محاولة تسجيل الدخول...")
            await client.start(phone_number) # سيتطلب إدخال الرمز إذا لم تكن هناك جلسة صالحة
        print("تم الاتصال بحساب Telegram بنجاح.")
    except Exception as e:
        print(f"فشل الاتصال بحساب Telegram: {e}")
        is_checking_complete = True
        return

    await test_bot_connection() # إرسال رسالة بدء الفحص

    crypto_pairs_from_binance = await get_binance_usdt_pairs()

    if not crypto_pairs_from_binance:
        print("لم يتم جلب أي أزواج عملات من Binance. إنهاء عملية الفحص الحالية.")
        is_checking_complete = True
        return

    # فتح ملف لحفظ الرموز الحلال (الكتابة فوق الملف القديم في كل مرة)
    with open(output_file, 'w', encoding='utf-8') as output:
        for pair_with_usdt in crypto_pairs_from_binance:
            # إزالة USDT من الزوج لإرساله إلى البوت
            # معالجة حالة مثل "USDTUSDT" أو أزواج غريبة أخرى قد لا تكون عملات أساسية
            if pair_with_usdt == "USDT": # حالة نادرة لكن للتحقق
                continue
            
            crypto_symbol_to_check = pair_with_usdt.removesuffix('USDT') # Python 3.9+

            if not crypto_symbol_to_check: # إذا كان الزوج هو "USDT" فقط
                print(f"تخطي زوج غير صالح: {pair_with_usdt}")
                continue

            # إذا كانت العملة قد تم فحصها مسبقًا في هذه الجلسة، تخطيها
            if crypto_symbol_to_check in checked_cryptos:
                print(f"العملة {crypto_symbol_to_check} (من الزوج {pair_with_usdt}) تم فحصها مسبقًا في هذه الجلسة.")
                # إذا كانت العملة موجودة في halal_cryptos من فحص سابق في نفس الجلسة، أعد كتابتها للملف
                if pair_with_usdt in halal_cryptos:
                     output.write(f"{pair_with_usdt}\n")
                continue

            print(f"--- بدء فحص الزوج: {pair_with_usdt} (العملة الأساسية: {crypto_symbol_to_check}) ---")
            # فحص العملة (بدون USDT)
            result_details = await check_crypto(crypto_symbol_to_check)
            
            if result_details and result_details.get("name"): # التأكد من أن النتيجة تحتوي على اسم العملة على الأقل
                # إضافة USDT إلى العملة وحفظها
                # pair_with_usdt هو الاسم الصحيح الذي تم جلبه من Binance
                if pair_with_usdt not in halal_cryptos:  # تجنب التكرار في مجموعة halal_cryptos
                    halal_cryptos.add(pair_with_usdt)
                    output.write(f"{pair_with_usdt}\n")  # حفظ العملة مع USDT
                    print(f"تمت إضافة {pair_with_usdt} إلى قائمة الحلال.")
                    # إرسال إشعار إلى بوت التليجرام عن العملة الحلال الجديدة
                    await send_halal_crypto_notification(result_details)
            else:
                print(f"لم يتم الحصول على نتيجة إيجابية أو تفاصيل كافية للعملة {crypto_symbol_to_check}.")


            # إضافة العملة إلى القائمة التي تم فحصها لهذه الجلسة
            checked_cryptos.add(crypto_symbol_to_check)
            
            # إضافة تأخير بسيط لتجنب إغراق بوت الفحص أو واجهة Binance (إذا كانت هناك استدعاءات أخرى)
            await asyncio.sleep(5) # زيادة التأخير قليلاً ليكون أكثر أمانًا مع بوت الفحص

    print(f"تم حفظ الرموز الحلال في ملف '{output_file}'.")
    print("تم الانتهاء من فحص جميع العملات بنجاح!")
    is_checking_complete = True  # تحديث حالة الفحص

    # استبدال ملف pairs.txt على GitHub
    if repo: # التحقق من أن repo تم تهيئته بنجاح
        update_github_file()
    else:
        print("لن يتم تحديث GitHub لأن المستودع لم يتم تهيئته بشكل صحيح.")


def update_github_file():
    """
    دالة لتحديث ملف pairs.txt على GitHub.
    """
    if not repo: # التأكد مرة أخرى قبل محاولة التحديث
        print("خطأ: لا يمكن تحديث GitHub لأن المستودع غير مهيأ.")
        return
    try:
        # قراءة محتوى ملف النتائج
        with open(output_file, 'r', encoding='utf-8') as file:
            content = file.read()
        
        if not content.strip() and os.path.exists(file_path):
            print("ملف النتائج فارغ. لن يتم تحديث الملف على GitHub بمحتوى فارغ إذا كان الملف موجودًا بالفعل.")
            # يمكنك اختيار حذف الملف على GitHub إذا كان هذا هو السلوك المطلوب
            # repo.delete_file(file_path, "Remove empty pairs.txt", current_file.sha)
            return

        try:
            # الحصول على الملف من المستودع للتحقق من وجوده والحصول على SHA
            current_file = repo.get_contents(file_path)
            repo.update_file(current_file.path, "تحديث قائمة العملات الحلال تلقائيًا", content, current_file.sha)
            print(f"تم تحديث ملف {file_path} على GitHub بنجاح.")
        except Exception as e_gh: # github.UnknownObjectException إذا لم يتم العثور على الملف
            if "Not Found" in str(e_gh) or "404" in str(e_gh):
                print(f"ملف {file_path} غير موجود على GitHub. سيتم إنشاؤه.")
                repo.create_file(file_path, "إنشاء قائمة العملات الحلال تلقائيًا", content)
                print(f"تم إنشاء ملف {file_path} على GitHub بنجاح.")
            else:
                raise # إعادة رمي الاستثناء إذا كان خطأ آخر
                
    except Exception as e:
        print(f"حدث خطأ أثناء تحديث الملف على GitHub: {e}")

# --- دوال Flask تبقى كما هي ---
@app.route('/', methods=['GET'])
def home():
    return """
    <h1>مرحبًا! هذا تطبيق Flask لفحص العملات الحلال من Binance باستخدام Telegram Bot.</h1>
    <p>يتم تحديث القائمة تلقائيًا كل ساعة.</p>
    <p><a href="/download-results" class="button">تحميل ملف النتائج (halal_crypto.txt)</a></p>
    <p><a href="/view-results" class="button">عرض النتائج مباشرة</a></p>
    <p><a href="/status" class="button">حالة الفحص الحالية</a></p>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background-color: #f4f4f4; color: #333; }
        h1 { color: #007bff; }
        .button { 
            display: inline-block; 
            padding: 10px 15px; 
            margin: 5px 0;
            background-color: #007bff; 
            color: white; 
            text-decoration: none; 
            border-radius: 5px; 
        }
        .button:hover { background-color: #0056b3; }
    </style>
    """

@app.route('/download-results', methods=['GET'])
def download_results():
    try:
        return send_file(output_file, as_attachment=True, download_name="halal_crypto.txt")
    except FileNotFoundError:
        return jsonify({"error": "لم يتم العثور على ملف النتائج. ربما لم تكتمل عملية الفحص بعد."}), 404

@app.route('/view-results', methods=['GET'])
def view_results():
    try:
        with open(output_file, 'r', encoding='utf-8') as file:
            content = file.read()
        if not content.strip():
            return "<p>ملف النتائج فارغ حاليًا. قد تكون عملية الفحص جارية أو لم يتم العثور على عملات حلال بعد.</p>"
        return f"<h1>العملات الحلال التي تم العثور عليها:</h1><pre>{content}</pre>"
    except FileNotFoundError:
        return jsonify({"error": "لم يتم العثور على ملف النتائج. ربما لم تكتمل عملية الفحص بعد."}), 404

@app.route('/status', methods=['GET'])
def status():
    global is_checking_complete
    if is_checking_complete:
        # محاولة قراءة آخر بضعة أسطر من ملف halal_crypto.txt لعرض آخر التحديثات
        last_updated_cryptos = []
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                last_updated_cryptos = f.readlines()[-5:] # آخر 5 عملات
        except FileNotFoundError:
            pass # الملف قد لا يكون موجودًا بعد

        status_message = "عملية الفحص مكتملة. في انتظار الدورة التالية."
        if last_updated_cryptos:
            status_message += "<br>آخر العملات المضافة:"
            status_message += "<pre>" + "".join(reversed(last_updated_cryptos)) + "</pre>" # عرض الأحدث أولاً
        return jsonify({"status": status_message, "checking_in_progress": False})
    else:
        return jsonify({"status": "عملية الفحص جارية حاليًا...", "checking_in_progress": True})


def run_async_check_all_cryptos():
    """
    دالة وسيطة لتشغيل check_all_cryptos في حلقة أحداث asyncio جديدة.
    """
    global is_checking_complete
    is_checking_complete = False # تعيين حالة الفحص إلى جارية
    print("بدء دورة فحص جديدة...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(check_all_cryptos())
    except Exception as e:
        print(f"حدث خطأ فادح أثناء تشغيل check_all_cryptos: {e}")
        is_checking_complete = True # التأكد من تحديث الحالة في حالة الخطأ
    finally:
        loop.close()
        print("دورة الفحص الحالية انتهت.")

# جدولة الفحص
def schedule_checking():
    # قم بتشغيل الفحص فورًا عند بدء التشغيل لأول مرة
    print("جدولة الفحص الأولي...")
    # تأخير بسيط قبل أول تشغيل للسماح لـ Flask بالبدء بشكل كامل
    initial_run_thread = threading.Timer(10.0, run_async_check_all_cryptos)
    initial_run_thread.start()

    # جدولة الفحص الدوري (مثلاً كل ساعة)
    schedule.every(1).hours.do(run_async_check_all_cryptos)
    # schedule.every().day.at("01:00").do(run_async_check_all_cryptos) # مثال: للتشغيل مرة يوميًا في الواحدة صباحًا

    print("تمت جدولة الفحص الدوري للعملات كل ساعة.")
    while True:
        schedule.run_pending()
        time.sleep(1)

# بدء الجدولة في خيط منفصل
if __name__ == '__main__':
    # بدء الفحص المجدول في خيط منفصل حتى لا يعيق تشغيل Flask
    scheduler_thread = threading.Thread(target=schedule_checking, daemon=True)
    scheduler_thread.start()
    
    # تشغيل تطبيق Flask
    # استخدم '0.0.0.0' لجعل الخادم متاحًا على الشبكة
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))

