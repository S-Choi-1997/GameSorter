from flask import Flask
from openai import OpenAI
import os
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

logger.info("Starting app initialization...")

# 모듈 임포트 로깅
logger.info("Importing modules...")
try:
    logger.info("Imported flask")
    logger.info("Imported openai")
    logger.info("Imported os")
    logger.info("Imported logging")
except Exception as e:
    logger.error(f"Failed to import modules: {e}")
    raise

app = Flask(__name__)

# OpenAI 초기화
logger.info("Initializing OpenAI client...")
try:
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        logger.error("OPENAI_API_KEY is not set")
        raise ValueError("OPENAI_API_KEY environment variable is required")
    client = OpenAI(api_key=api_key)
    logger.info("OpenAI client initialized successfully")
except ValueError as ve:
    logger.error(f"OpenAI initialization failed due to missing API key: {ve}")
    raise
except Exception as e:
    logger.error(f"Unexpected error during OpenAI initialization: {e}")
    raise

# OpenAI 번역 함수
def translate_with_gpt(text, src_lang='ja', dest_lang='ko'):
    if not text:
        return ''
    try:
        response = client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {'role': 'system', 'content': f'Translate the following {src_lang} text to {dest_lang} accurately.'},
                {'role': 'user', 'content': text}
            ],
            max_tokens=100
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"GPT translation error: {e}")
        return text

@app.route('/')
def hello():
    return "Hello, World!"

@app.route('/translate/<text>')
def translate(text):
    translated = translate_with_gpt(text)
    return {"original": text, "translated": translated}

logger.info("App initialization completed successfully")