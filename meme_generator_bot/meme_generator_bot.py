import io
import base64
import math
import requests
import os
from PIL import Image, ImageFont, ImageDraw 
from telegram.ext import (
    Updater, 
    CommandHandler, 
    MessageHandler, 
    Filters, 
    CallbackContext, 
    InlineQueryHandler, 
    CallbackQueryHandler, 
    ConversationHandler
)
from telegram import (
    InlineQueryResultArticle, 
    ParseMode, 
    InputTextMessageContent, 
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    InlineQueryResultPhoto,
    ReplyKeyboardMarkup, 
    ReplyKeyboardRemove
)
from telegram.utils.helpers import escape_markdown, mention_html
from telegram.error import TelegramError

import logging
import yaml
import json
import re
# import arrow
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(funcName)s: %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.environ.get("PORT", "8443"))
IMAGEBAN_CLIENT_ID = os.getenv("IMAGEBAN_CLIENT_ID")
IMAGEBAN_SECRET_KEY = os.getenv("IMAGEBAN_SECRET_KEY")
IMGUR_ACCESS_TOKEN = os.getenv("IMGUR_ACCESS_TOKEN")

help_msg = """Бот для тех случаев, когда тебе лень искать онлайн генератор мемов, но очень хочется выпендриться.
Как пользоваться:
В любом чате или в личке вводим 
<code>@awesomeMemeGeneratorBot </code>
Бот покажет список доступных мемов и сколько нужно текстов

Чтобы выбрать мем надо ввести
<code>@awesomeMemeGeneratorBot номер текст1
текст2 и т.д.</code>

автор бота @dmastr
вы можете помочь развитию бота прислав ваш любимый мем, где есть место для текста
эти люди помогали в сборе мемов:
@lion_hat
"""
IMG_API_APP = "imageban_api"


class ImagebanApi:
    def __init__(self):
        # client_id = IMAGEBAN_CLIENT_ID
        secret_key = IMAGEBAN_SECRET_KEY
        self.secret_key = secret_key
        self.base_url = "https://api.imageban.ru/v1"
        s = requests.Session()
        s.headers.update({"Authorization": "TOKEN "+IMAGEBAN_CLIENT_ID})
        self.api = s
    
    def image_upload(self, image, use_auth=False):
        data={"image": image}
        if use_auth:
            data["secret_key"] = self.secret_key
        return self.api.post(self.base_url, data=data)

class ImgurApi:
    def __init__(self):
        s = requests.Session()
        s.headers.update({"Authorization": "Bearer "+IMGUR_ACCESS_TOKEN})
        # s.headers.update({"Authorization": "Client-ID "+client_id})
        self.base_url = "https://api.imgur.com/3/"
        self.api = s
    
    def image_upload(self, image):
        url = "image"
        return self.api.post(self.base_url+url, data={"image": image})

    def image_delete(self, image_delete_hash):
        url = f"image/{image_delete_hash}"
        return self.api.delete(self.base_url+url)


def get_image_link(image, img_api) -> str:
    def dict_search(dct, path):
        dct_tmp = dct
        for p in path:
            dct_tmp = dct_tmp.get(p, {})
        return dct_tmp
    link = ""    
    status = ["status"]
    link = ["data", "link"]
    func = lambda x: x
    if IMG_API_APP=="imageban_api":
        func = lambda x: base64.b64encode(x)
    elif IMG_API_APP=="imgur_api":
        pass
    img_info = img_api.image_upload(func(image["img"]))
    img_info = img_info.json()
    
    if dict_search(img_info, status)==200:
        link = dict_search(img_info, link)
    else:
        logger.error(img_info)
    return link


def text_wrapper(text: str, ratio: list=[1, 1]) -> str:
    words = text.split()
    length = len(words)
    width, height = ratio
    if length==2 and width>2:
        width = 1
        height = 2
    while length>width*height:
        width += 1
        height += 1
    text_wraped = "\n".join([" ".join(words[i:i+width]) for i in range(0, length, width)])
    return text_wraped    


def sign(num, border) -> int:
    return -1 if num<border else 1


def image_resize(image_editable, text_wrapped: str, font: str, size_cap: list, font_size: int=50) -> float:
    FONT_STEP = 5
    FONT_MARGIN_L = 0.1
    FONT_MARGIN_U = 0.0
    MIN_FONT_SIZE = 8
    title_font = ImageFont.truetype(font, font_size)
    size = image_editable.multiline_textsize(text_wrapped, font=title_font)
    size_x, size_y = size
    size_cap_x, size_cap_y = size_cap
    size_adjust = max(size_x/size_cap_x, size_y/size_cap_y)
    if size_adjust>=(1-FONT_MARGIN_L) and size_adjust<=(1+FONT_MARGIN_U):
        return max(font_size, MIN_FONT_SIZE)
    else:
        font_size -= int(FONT_STEP*math.sqrt(size_adjust)*sign(size_adjust, 1))
        return image_resize(image_editable, text_wrapped, font, size_cap, font_size)


def text_insert(image_editable, text: str, ratio: list, position: list, color: list, font: str, size_cap: list):
    text_wrapped = text_wrapper(text, ratio)
    try:
        font_size = image_resize(image_editable, text_wrapped, font, size_cap)
    except RecursionError:
        font_size = 50
    title_font = ImageFont.truetype(font, font_size)
    position = tuple(position)
    color = tuple(color)
    image_editable.multiline_text(position, text_wrapped, color, font=title_font)
    return image_editable


def image_edit(img_idx: str, texts: list, config: list) -> dict:
    b = io.BytesIO()
    cur_command = config[int(img_idx)-1]
    err = "Не найден мем с именем"
    err_code = 1
    if cur_command:
        # cur_command = cur_command[0]
        err = "Маловато текстов! Бот хочет {1}, а ты присылаешь {0}".format(len(texts), len(cur_command["texts"]))
        if len(texts)==len(cur_command["texts"]) and texts[0]:
            full_url = cur_command["full_url"]
            text_params_ls = cur_command["texts"]
            # my_image = Image.open(f"./meme_images/{filename}")
            my_image = Image.open(requests.get(full_url, stream=True).raw)
            image_editable = ImageDraw.Draw(my_image)
            for text, text_params in zip(texts, text_params_ls):
                position = text_params["position"]
                color = text_params["color"]
                font = "./fonts/{}".format(text_params.get("font", "Roboto-Bold.ttf"))
                size_cap = text_params["size_cap"]
                ratio = text_params.get("ratio", [1, 1])
                
                image_editable = text_insert(
                    image_editable,
                    text=text,
                    ratio=ratio,
                    position=position,
                    color=color,
                    font=font,
                    size_cap=size_cap
                )  
            err = ""
            err_code = 0
            my_image.save(b, "JPEG")
    return {"err_code": err_code, "img": b.getvalue(), "err_msg": err}


def create_title(img_idx: int, texts: list) -> str:
    title = ""
    text_template = " ".join([f"текст{i}" for i in range(1, len(texts)+1)])
    # if len(texts)>1:
    #     title += "{} текста (разделять переносом строки). ".format(len(texts))
    title += "чтобы отправить мем вводи: {0} {1}".format(img_idx, text_template)
    return title


def show_available_meme(update: Update, context: CallbackContext) -> None:
    def create_template(img_idx: int) -> str:
        meme = config[img_idx-1]
        texts = "\n".join([f"Текст {i}" for i, text in enumerate(meme["texts"], 1)])
        template = "Чтобы отправить этот мем введи текст\n<code>@awesomeMemeGeneratorBot {0} {1}</code>".format(img_idx, texts)
        return InputTextMessageContent(message_text=template, parse_mode=ParseMode.HTML)
    query = update.inline_query.query
    config = context.bot_data["config"]
    short_name = ""
    img_idx = "-1"
    pat = re.compile(r"([\wА-Яа-я\d]+)\s?(.*)", re.DOTALL)
    pat_multi = re.compile(r"([\wА-Яа-я\d]+).*", re.DOTALL)
    if query:
        parsed = pat.search(query)
        if parsed:
            img_idx, texts = parsed.groups()
            texts = texts.strip().split("\n")
            img_edited = image_edit(img_idx, texts, config)
            short_name = config[int(img_idx)-1]["short_name"]
            if img_edited["err_code"]==0:
                link = get_image_link(img_edited, context.bot_data[IMG_API_APP])
                logger.info("User {0} request meme, url {1}".format(update.effective_user.username, link))
                if link:
                    results = [
                        InlineQueryResultPhoto(
                            id=short_name,
                            title=short_name,
                            photo_width=500,
                            photo_height=500,
                            photo_url=link,
                            thumb_url=link
                        )
                    ]
                    update.inline_query.answer(results)
                    # logger.info("User {0} request meme, url {1}".format(update.effective_user.username, link))
            else:
                pass
        elif pat_multi.search(query):
            img_idx = pat_multi.search(query).groups()[0]
    results = [
        InlineQueryResultArticle(
            id=meme.get("filename"),
            # title="{0} - {1} текст(а)".format(meme["short_name"], len(meme["texts"])),
            title="несколько текстов - перенос строки",
            description=create_title(i, meme["texts"]),
            thumb_url=meme.get("url"),
            url=meme.get("url"),
            thumb_width=800,
            thumb_height=800,
            input_message_content=create_template(i)
        )
        for i, meme in enumerate(config, 1)
        if meme.get("url") 
        and (img_idx=="-1" or i==int(img_idx))
    ]
    update.inline_query.answer(results)


def start(update: Update, context: CallbackContext) -> None:
    if update.message.chat.id==40322523:
        update.message.reply_text("Welcome, meme lord!")
    else:
        update.message.reply_text(help_msg, parse_mode=ParseMode.HTML)

def help(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(help_msg, parse_mode=ParseMode.HTML)


def update_config_first(context: CallbackContext) -> None:
    with open("bot_config.yml") as f:
        context.bot_data["config"] = yaml.load(f, Loader=yaml.FullLoader)


def img_api_init(context: CallbackContext) -> None:
    context.bot_data["imgur_api"] = ImgurApi()
    context.bot_data["imageban_api"] = ImagebanApi()


def update_config(update: Update, context: CallbackContext) -> None:
    with open("bot_config.yml") as f:
        context.bot_data["config"] = yaml.load(f, Loader=yaml.FullLoader)


def delete_old_images(context: CallbackContext) -> None:
    imgur_api = context.bot_data["imgur_api"]
    for img_hash in context.bot_data.get("imgdeletehash", []):
        imgur_api.image_delete(img_hash)


def main():
    updater = Updater(token=BOT_TOKEN, use_context=True)
    dispatcher = updater.dispatcher
    job_queue = updater.job_queue
    create_meme_inline_handler = InlineQueryHandler(
        show_available_meme,
        pass_update_queue=True
    )
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("help", help))
    # dispatcher.add_handler(CommandHandler("upd", update_config))
    dispatcher.add_handler(create_meme_inline_handler)

    job_queue.run_once(update_config_first, when=0)
    job_queue.run_once(img_api_init, when=0)
    job_queue.run_repeating(delete_old_images, interval=3600, first=3600)

    updater.start_webhook(listen="0.0.0.0", port=PORT, url_path=BOT_TOKEN)
    updater.bot.setWebhook('https://mem-generator.herokuapp.com/' + BOT_TOKEN)

    # updater.start_polling()
    updater.idle()



if __name__ == "__main__":
    main()
