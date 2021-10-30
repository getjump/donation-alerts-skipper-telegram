.PHONY: dev test lint start dev_build dev_start dev_test

all: dev_start

# docker stuff
build:
	docker compose build

start:
	docker compose up -d && docker compose logs -f --tail=10

stop:
	docker compose stop

down:
	docker compose down

docker_test:
	docker compose run --rm bot pytest

test:
	export PYTHONPATH=./bot && pytest

lint:
	flake8 ./bot --count --select=E9,F63,F7,F82 --show-source --statistics
	flake8 ./bot --count --exit-zero --max-complexity=10 --max-line-length=127 --statistics
	mypy --config-file mypy.ini ./bot

format:
	black ./bot
