.PHONY: install run lint test format docker-up docker-down

install:
	python -m pip install --upgrade pip
	pip install -e .[dev]

run:
	python -m app.main

lint:
	ruff check src tests

format:
	ruff format src tests

test:
	pytest -q

docker-up:
	docker compose up --build

docker-down:
	docker compose down
