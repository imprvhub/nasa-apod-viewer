from flask import Flask, render_template, request, jsonify, send_file
import requests
from PIL import Image
from io import BytesIO
import datetime
import logging
import os
from functools import wraps
from selenium import webdriver
import base64

app = Flask(__name__)

options = webdriver.ChromeOptions()
options.add_argument('headless')  
driver = webdriver.Chrome(options=options)

class NasaApiException(Exception):
    """Raised for any exception caused by a call to the Nasa API"""

class RateLimitException(NasaApiException):
    """Raised when you have exceeded your rate limit"""

def api_get(url, payload):
    payload = dict((k, v) for k, v in payload.items() if v)
    payload['api_key'] = api_key()
    response = requests.get(url, params=payload)
    if response.status_code == 429:
        raise RateLimitException('You have exceeded your rate limit')
    response.raise_for_status()
    body = response.json()
    if 'error' in body:
        raise NasaApiException(body['error'])

    ratelimit_limit = int(response.headers['x-ratelimit-limit'])
    ratelimit_remaining = int(response.headers['x-ratelimit-remaining'])
    percent = ratelimit_remaining / ratelimit_limit
    if percent < 0.1:
        api_logger().warn(
            "Only {:3.1f}% of your rate limit is remaining!".format(percent * 100)
        )

    return body

def external_api_get(url, payload):
    payload = dict((k, v) for k, v in payload.items() if v)
    response = requests.get(url, params=payload)
    response.raise_for_status()
    body = response.json()
    return body

def api_key():
    return os.environ["NASA_API_KEY"]

def api_logger():
    return logging.getLogger('nasa_logger')

def optional(validator):
    '''Mark a validation as optional (allow None)'''
    @wraps(validator)
    def wrapper(*args, **kwargs):
        value = args[0]
        return None if value is None else validator(*args, **kwargs)
    return wrapper

@optional
def optional_date(input):
    return nasa_date(input)

def nasa_date(input):
    try:
        datetime.datetime.strptime(input, '%Y-%m-%d')
        return input
    except ValueError:
        raise ValueError('Incorrect date format, should be YYYY-MM-DD')

@optional
def optional_int(input):
    return nasa_int(input)

def nasa_int(input):
    if isinstance(input, int):
        return input
    raise ValueError('Expected an int')

@optional
def optional_float(input):
    return nasa_float(input)

def nasa_float(input):
    if isinstance(input, float):
        return input
    raise ValueError('Expected a float')

class NasaApiObject(object):
    def __init__(self, **kwargs):
        for prop in self.Meta.properties:
            val = None
            if prop in kwargs:
                val = kwargs[prop]
            setattr(self, '{0}'.format(prop), val)

    @classmethod
    def from_response(cls, response):
        kwargs = {}
        for prop in cls.Meta.properties:
            try:
                kwargs[prop] = response[prop]
            except KeyError:
                pass
        return cls(**kwargs)

def apod(date=None, concept_tags=None):
    payload = {
        'date': optional_date(date),
        'concept_tags': concept_tags,
    }
    return Apod.from_response(api_get(
        'https://api.nasa.gov/planetary/apod',
        payload,
    ))

class Apod(NasaApiObject):
    """NASA's Astronomy Picture of the Day"""
    class Meta(object):
        properties = ['url', 'title', 'explanation', 'concepts']

    def __init__(self, **kwargs):
        super(Apod, self).__init__(**kwargs)
        self._image = None
        if self.concepts is not None:
            self.concepts = self.concepts.values()

    @property
    def image(self):
        if self._image is None:
            self._image = Image.open(BytesIO(requests.get(self.url).content))
        return self._image

@app.route('/')
def apod_images():
    picture = apod('2024-01-09')
    return render_template('index.html', images=[picture])

@app.route('/update_image')
def update_image():
    try:
        selected_date = request.args.get('date')
        picture = apod(selected_date)
        print("Title:", picture.title)
        print("Explanation:", picture.explanation)
        return jsonify({'url': picture.url, 'title': "'" + picture.title + "'", 'explanation': 'Description: ' + picture.explanation})
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({'error': 'Image not found'}), 404
    
@app.route('/generate_card_screenshot')
def generate_card_screenshot():
    try:
        url = request.url_root
        driver.get(url)
        height = driver.execute_script("return document.body.scrollHeight")
        driver.set_window_size(1920, height)

        driver.execute_script("""
            var elements = document.querySelectorAll("#recommendations, #datePickerContainer, #navigationArrows, #iconContainer, #expandIconContainer, #socialsContainer, #userTerms");
            elements.forEach(function(element) {
                element.style.display = 'none';
            });
            document.body.style.height = '100%';
            document.documentElement.style.height = '100%';
            document.body.parentNode.style.overflowY = 'hidden';
            """)
        driver.execute_script("""
            document.body.style.backgroundImage = 'url("/static/images/background-card.webp")';
        """)
        screenshot = driver.get_screenshot_as_png()

        driver.execute_script("""
            document.body.style.backgroundImage = '';
        """)
        screenshot_path = os.path.join(app.static_folder, 'screenshots', 'screenshot.png')
        with open(screenshot_path, 'wb') as f:
            f.write(screenshot)
        screenshot_base64 = base64.b64encode(screenshot).decode('utf-8')

        driver.execute_script("""
            var elements = document.querySelectorAll("#recommendations, #datePickerContainer, #navigationArrows, #iconContainer, #expandIconContainer, #socialsContainer, #userTerms");
            elements.forEach(function(element) {
                element.style.display = 'block';
            });
            document.body.style.height = '';
            document.documentElement.style.height = '';
            document.body.parentNode.style.overflowY = '';
            """)

        return jsonify({'screenshot': screenshot_base64, 'screenshot_path': screenshot_path})
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({'error': 'Error generating screenshot'}), 500
    

@app.route('/preview')
def card_preview():
    image_url = "/static/screenshots/screenshot.png"
    image_title = request.args.get('title')
    image_description = request.args.get('description')
    return render_template('preview.html', image_url=image_url, title=image_title, description=image_description)

    
@app.route('/user_agreements')
def user_agreements():
    return render_template('user_agreements.html')

if __name__ == '__main__':
    app.run(debug=True)
