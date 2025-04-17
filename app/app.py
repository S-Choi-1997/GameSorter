from flask import Flask
from openai import OpenAI
import os
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)

logger.info("Initializing OpenAI client...")
try:
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        logger.error("OPENAI_API_KEY is not set")
        raise ValueError("OPENAI_API_KEY environment variable is required")
    client = OpenAI(api_key=api_key)
    logger.info("OpenAI client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize OpenAI client: {e}")
    raise

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