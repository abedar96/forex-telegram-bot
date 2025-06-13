import logging
import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Updater, # تم التغيير من Application
    CommandHandler,
    CallbackQueryHandler,
    CallbackContext # تم إضافة هذا ليتوافق مع Updater
)
import asyncio
import yfinance as yf
import pandas as pd
import pandas_ta as ta

# قم بتمكين التسجيل (Logging) للمساعدة في تصحيح الأخطاء
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- بيانات ثابتة (يمكن توسيعها) ---
# أزواج العملات المتاحة
# ملاحظة: yfinance يستخدم صيغة "X=Y" لأزواج العملات بدلاً من "X/Y"
CURRENCY_PAIRS = {
    "EURUSD=X": "EUR/USD",
    "GBPUSD=X": "GBP/USD",
    "USDJPY=X": "USD/JPY",
    "AUDUSD=X": "AUD/USD",
    "USDCAD=X": "USD/CAD",
    "XAUUSD=X": "الذهب / الدولار (XAU/USD)", # الذهب مقابل الدولار
    "GC=F": "العقود الآجلة للذهب (GC=F)", # خيار آخر للذهب، قد يكون أكثر سيولة
    "SI=F": "العقود الآجلة للفضة (SI=F)", # الفضة
}

# الإطارات الزمنية المتاحة لـ yfinance
# يرجى ملاحظة أن yfinance لديه قيود على توفر البيانات للإطارات الزمنية الصغيرة جداً والبيانات التاريخية الطويلة.
# على سبيل المثال، إطار دقيقة واحدة (1m) قد يكون متاحاً فقط لآخر 7 أيام.
TIME_FRAMES = {
    "1m": "دقيقة واحدة (1m) - (بيانات محدودة)",
    "2m": "دقيقتان (2m) - (بيانات محدودة)",
    "5m": "خمس دقائق (5m)",
    "15m": "خمس عشرة دقيقة (15m)",
    "30m": "ثلاثون دقيقة (30m)",
    "60m": "ساعة واحدة (60m)",
    "1h": "ساعة واحدة (1h)", # بديل لـ 60m
    "1d": "يوم واحد (1d)",
    "5d": "خمسة أيام (5d)",
    "1wk": "أسبوع واحد (1wk)",
    "1mo": "شهر واحد (1mo)",
}

# --- وظائف معالجة الأوامر والاستجابات ---

async def start(update: Update, context: CallbackContext) -> None:
    """يرسل رسالة ترحيب ويعرض أزرار أزواج العملات."""
    user = update.effective_user
    await update.message.reply_html(
        f"مرحباً {user.mention_html()}! أنا بوت التحليل الفني للفوركس.\n"
        "الرجاء اختيار زوج العملات الذي تود تحليله:",
        reply_markup=get_currency_pairs_keyboard(),
    )

def get_currency_pairs_keyboard() -> InlineKeyboardMarkup:
    """ينشئ لوحة مفاتيح (Inline Keyboard) لأزواج العملات."""
    keyboard = []
    for code, name in CURRENCY_PAIRS.items():
        # يتم استخدام 'select_pair_' كبادئة لتمييز استجابات أزواج العملات
        keyboard.append([InlineKeyboardButton(name, callback_data=f"select_pair_{code}")])
    return InlineKeyboardMarkup(keyboard)

def get_time_frames_keyboard() -> InlineKeyboardMarkup:
    """ينشئ لوحة مفاتيح (Inline Keyboard) للإطارات الزمنية."""
    keyboard = []
    for code, name in TIME_FRAMES.items():
        # يتم استخدام 'select_tf_' كبادئة لتمييز استجابات الإطارات الزمنية
        keyboard.append([InlineKeyboardButton(name, callback_data=f"select_tf_{code}")])
    return InlineKeyboardMarkup(keyboard)

async def button_callback_handler(update: Update, context: CallbackContext) -> None:
    """يتعامل مع نقرات الأزرار التفاعلية (Inline Keyboard)."""
    query = update.callback_query
    await query.answer() # يجب الرد على الـ CallbackQuery لتجنب ظهور "تحميل" للمستخدم

    data = query.data

    if data.startswith("select_pair_"):
        # المستخدم اختار زوج عملات
        selected_pair_code = data.replace("select_pair_", "")
        context.user_data['selected_pair'] = selected_pair_code
        logger.info(f"المستخدم {query.from_user.id} اختار زوج: {CURRENCY_PAIRS.get(selected_pair_code, selected_pair_code)}")

        # استخدام query.edit_message_text بدلاً من update.message.reply_html
        await query.edit_message_text(
            f"لقد اخترت: <b>{CURRENCY_PAIRS.get(selected_pair_code, selected_pair_code)}</b>.\n"
            "الآن، الرجاء اختيار الإطار الزمني للتحليل:",
            parse_mode='HTML',
            reply_markup=get_time_frames_keyboard(),
        )

    elif data.startswith("select_tf_"):
        # المستخدم اختار إطار زمني
        selected_tf_code = data.replace("select_tf_", "")
        context.user_data['selected_timeframe'] = selected_tf_code
        logger.info(f"المستخدم {query.from_user.id} اختار إطار زمني: {TIME_FRAMES.get(selected_tf_code, selected_tf_code)}")

        selected_pair_yf = context.user_data.get('selected_pair') # هذا هو الرمز الذي يستخدمه yfinance
        selected_timeframe_yf = context.user_data.get('selected_timeframe')

        # الحصول على الاسم المعروض للزوج والإطار الزمني
        display_pair_name = CURRENCY_PAIRS.get(selected_pair_yf, selected_pair_yf)
        display_timeframe_name = TIME_FRAMES.get(selected_timeframe_yf, selected_timeframe_yf)

        if selected_pair_yf and selected_timeframe_yf:
            await query.edit_message_text(
                f"جارٍ تحليل <b>{display_pair_name}</b> على إطار <b>{display_timeframe_name}</b>...\n"
                "قد يستغرق هذا بضع لحظات.",
                parse_mode='HTML'
            )
            
            try:
                # 1. جلب البيانات باستخدام yfinance
                # تحديد فترة جلب البيانات بناءً على الإطار الزمني لتجنب الأخطاء مع yfinance
                # يرجى ملاحظة أن 'interval' يجب أن يتوافق مع 'period'
                if selected_timeframe_yf in ["1m", "2m", "5m", "15m", "30m", "60m", "1h"]:
                    # للفواصل الزمنية القصيرة، الفترة يجب أن تكون قصيرة أيضاً
                    period = "7d" # 7 أيام كحد أقصى للفواصل الزمنية الأقصر
                elif selected_timeframe_yf in ["1d"]:
                    period = "6mo" # 6 أشهر لبيانات اليوم
                else:
                    period = "1y" # سنة واحدة أو أكثر للإطارات الأكبر

                forex_data = await get_forex_data_yf(selected_pair_yf, selected_timeframe_yf, period)

                if forex_data is None or forex_data.empty:
                    await query.message.reply_html( # استخدام reply_html لضمان التنسيق
                        f"عذراً، لم أتمكن من جلب بيانات لـ <b>{display_pair_name}</b> على إطار <b>{display_timeframe_name}</b>.<br>"
                        "قد تكون البيانات غير متاحة أو هناك مشكلة مؤقتة. الرجاء المحاولة لاحقاً أو اختيار إطار زمني آخر."
                    )
                    return # إنهاء الوظيفة هنا

                # 2. إجراء التحليل الفني
                analysis_result = await perform_technical_analysis(forex_data, selected_pair_yf, selected_timeframe_yf)

                # 3. إرسال نتيجة التحليل
                await send_analysis_result(query.message, display_pair_name, display_timeframe_name, analysis_result)

            except Exception as e:
                logger.error(f"حدث خطأ أثناء التحليل: {e}", exc_info=True)
                await query.message.reply_html( # استخدام reply_html لضمان التنسيق
                    "عذراً، حدث خطأ أثناء محاولة إجراء التحليل. الرجاء المحاولة لاحقاً."
                )
        else:
            await query.edit_message_text(
                "عذراً، لم يتم تحديد زوج العملات أو الإطار الزمني بشكل صحيح. الرجاء البدء من جديد باستخدام أمر /start.",
                parse_mode='HTML'
            )

# --- وظائف جلب البيانات والتحليل الفعلية ---

async def get_forex_data_yf(symbol: str, interval: str, period: str) -> pd.DataFrame:
    """
    جلب بيانات الفوركس التاريخية باستخدام yfinance.
    :param symbol: رمز زوج العملات (مثلاً "EURUSD=X").
    :param interval: الإطار الزمني (مثلاً "1h", "1d").
    :param period: الفترة التاريخية لجلب البيانات (مثلاً "7d", "6mo", "1y").
    :return: DataFrame من Pandas يحتوي على البيانات.
    """
    logger.info(f"جلب بيانات {symbol} على إطار {interval} لمدة {period}...")
    try:
        ticker = yf.Ticker(symbol)
        # استخدام .history() لجلب البيانات
        data = ticker.history(interval=interval, period=period)
        if data.empty:
            logger.warning(f"لم يتم العثور على بيانات لـ {symbol} بإطار {interval} وفترة {period}. قد تكون البيانات غير متوفرة أو تجاوزت حدود yfinance.")
        return data
    except Exception as e:
        logger.error(f"خطأ في جلب البيانات من yfinance لـ {symbol}: {e}", exc_info=True)
        return pd.DataFrame() # إرجاع DataFrame فارغ في حالة الخطأ


async def perform_technical_analysis(data: pd.DataFrame, symbol: str, timeframe: str) -> str:
    """
    إجراء التحليل الفني باستخدام pandas_ta.
    :param data: DataFrame من Pandas يحتوي على بيانات السعر (Open, High, Low, Close, Volume).
    :param symbol: رمز زوج العملات.
    :param timeframe: الإطار الزمني للتحليل.
    :return: نص يحتوي على نتائج التحليل.
    """
    if data.empty:
        return "لا توجد بيانات كافية لإجراء التحليل."

    # التأكد من أن الأعمدة المطلوبة موجودة
    required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
    if not all(col in data.columns for col in required_cols):
        return "بيانات غير مكتملة لإجراء التحليل الفني."

    # --- حساب المؤشرات الفنية باستخدام pandas_ta ---
    # مثال: المتوسط المتحرك البسيط (SMA) لمدة 20 و 50 فترة
    data.ta.sma(length=20, append=True)
    data.ta.sma(length=50, append=True)

    # مثال: مؤشر القوة النسبية (RSI) لمدة 14 فترة
    data.ta.rsi(length=14, append=True)

    # مثال: مؤشر الماكد (MACD)
    data.ta.macd(append=True)

    # --- بناء قراءات تحليلية بناءً على المؤشرات ---
    analysis_text = []

    # التحليل الأخير
    last_row = data.iloc[-1]
    prev_row = data.iloc[-2] if len(data) >= 2 else None

    # تحليل السعر الحالي
    current_price = last_row['Close']
    analysis_text.append(f"<b>السعر الحالي:</b> {current_price:.5f}")

    # تحليل المتوسطات المتحركة (SMA)
    sma_20 = last_row.get('SMA_20')
    sma_50 = last_row.get('SMA_50')
    
    if pd.notna(sma_20) and pd.notna(sma_50):
        analysis_text.append(f"<b>SMA (20):</b> {sma_20:.5f}")
        analysis_text.append(f"<b>SMA (50):</b> {sma_50:.5f}")
        if current_price > sma_20 and current_price > sma_50:
            analysis_text.append("✅ السعر فوق المتوسطين المتحركين (20 و 50)، مما يشير إلى <b>اتجاه صاعد</b>.")
        elif current_price < sma_20 and current_price < sma_50:
            analysis_text.append("❌ السعر تحت المتوسطين المتحركين (20 و 50)، مما يشير إلى <b>اتجاه هابط</b>.")
        else:
            analysis_text.append("↔️ السعر يتداول بين المتوسطين المتحركين، مما يشير إلى <b>اتجاه جانبي</b> أو عدم وضوح.")
        
        if prev_row is not None and pd.notna(prev_row.get('SMA_20')) and pd.notna(prev_row.get('SMA_50')):
            # تقاطع المتوسطات المتحركة (Golden Cross / Death Cross)
            if sma_20 > sma_50 and prev_row['SMA_20'] < prev_row['SMA_50']:
                analysis_text.append("✨ <b>تقاطع صاعد (Golden Cross) محتمل!</b> (SMA20 يخترق SMA50 للأعلى) - إشارة صعودية.")
            elif sma_20 < sma_50 and prev_row['SMA_20'] > prev_row['SMA_50']:
                analysis_text.append("🔻 <b>تقاطع هابط (Death Cross) محتمل!</b> (SMA20 يخترق SMA50 للأسفل) - إشارة هبوطية.")

    # تحليل مؤشر القوة النسبية (RSI)
    rsi_value = last_row.get('RSI_14')
    if pd.notna(rsi_value):
        analysis_text.append(f"<b>RSI (14):</b> {rsi_value:.2f}")
        if rsi_value > 70:
            analysis_text.append("⚠️ RSI فوق 70، يشير إلى منطقة <b>تشبع شراء</b> محتملة.")
        elif rsi_value < 30:
            analysis_text.append("✅ RSI تحت 30، يشير إلى منطقة <b>تشبع بيع</b> محتملة.")
        else:
            analysis_text.append("📊 RSI يتداول في المنطقة المحايدة (30-70).")

    # تحليل مؤشر الماكد (MACD)
    macd_value = last_row.get('MACD_12_26_9')
    macd_signal = last_row.get('MACDs_12_26_9')
    macd_hist = last_row.get('MACDh_12_26_9')

    if pd.notna(macd_value) and pd.notna(macd_signal) and pd.notna(macd_hist):
        analysis_text.append(f"<b>MACD:</b> {macd_value:.4f}")
        analysis_text.append(f"<b>MACD Signal:</b> {macd_signal:.4f}")
        analysis_text.append(f"<b>MACD Histogram:</b> {macd_hist:.4f}")

        if macd_value > macd_signal and (prev_row is None or prev_row.get('MACD_12_26_9', 0) <= prev_row.get('MACDs_12_26_9', 0)):
            analysis_text.append("📈 خط MACD عبر خط الإشارة للأعلى، إشارة <b>صعودية</b> محتملة.")
        elif macd_value < macd_signal and (prev_row is None or prev_row.get('MACD_12_26_9', 0) >= prev_row.get('MACDs_12_26_9', 0)):
            analysis_text.append("📉 خط MACD عبر خط الإشارة للأسفل، إشارة <b>هبوطية</b> محتملة.")
        else:
            analysis_text.append("📊 MACD لا يعطي إشارة واضحة حالياً أو يستمر في اتجاهه الحالي.")

    # يمكنك إضافة المزيد من المؤشرات والتحليلات هنا
    # مثال: Bollinger Bands, Stochastic Oscillator, Fibonacci Retracements

    # تجميع النص النهائي
    final_analysis = "\n".join(analysis_text)
    if not analysis_text:
        final_analysis = "لم أتمكن من إجراء تحليل شامل حالياً للبيانات المتاحة."

    return final_analysis

async def send_analysis_result(message, display_pair: str, display_timeframe: str, analysis_data: str) -> None:
    """يرسل نتائج التحليل إلى المستخدم."""
    formatted_result = (
        f"<b>نتائج تحليل {display_pair} على إطار {display_timeframe}:</b>\n\n"
        f"{analysis_data}\n\n"
        "لإجراء تحليل جديد، اضغط /start."
    )
    await message.reply_html(formatted_result) # استخدام reply_html لضمان التنسيق

# --- وظيفة إعداد البوت الرئيسية (main) المُعدلة ---
def main() -> None:
    """يبدأ تشغيل البوت."""
    # رمز البوت الخاص بك
    # أفضل طريقة لجلب رمز البوت هي من متغيرات البيئة.
    # عند النشر على Render، ستقوم بتعيين متغير بيئة يسمى BOT_TOKEN.
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    if not BOT_TOKEN:
        logger.error("لم يتم العثور على رمز البوت. يرجى تعيين متغير البيئة BOT_TOKEN.")
        exit(1) # إيقاف البوت إذا لم يتم العثور على الرمز

    # تغيير طريقة التهيئة لـ python-telegram-bot v13.x
    updater = Updater(BOT_TOKEN)
    dispatcher = updater.dispatcher

    # إضافة معالجات الأوامر
    dispatcher.add_handler(CommandHandler("start", start))

    # إضافة معالج لاستجابات الأزرار (Callback Queries)
    dispatcher.add_handler(CallbackQueryHandler(button_callback_handler))

    logger.info("البوت بدأ العمل...")
    # ابدأ تشغيل البوت
    updater.start_polling()
    updater.idle() # لتشغيل البوت حتى يتم إيقافه يدوياً

if __name__ == "__main__":
    main()
