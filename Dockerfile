FROM python:latest

ENV PYTHONPATH /app/bot

COPY . /app
WORKDIR /app

RUN apt-get -y update && apt-get install -y ffmpeg

COPY ./requirements.txt /app/requirements.txt

RUN python -m pip install -r ./requirements.txt

CMD ["python", "bot.py"]
