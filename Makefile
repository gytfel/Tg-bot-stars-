.PHONY: install run check test seed docker-up docker-logs deploy

install:            ## зависимости в venv
	python3 -m venv venv && venv/bin/pip install -r requirements-dev.txt

run:                ## запустить бота локально
	python bot.py

check:              ## самодиагностика (.env, база, связь с Telegram)
	python doctor.py

test:               ## прогнать тесты
	python -m pytest -q

seed:               ## демо-каталог
	python seed.py

docker-up:          ## собрать и поднять в Docker
	docker compose up -d --build

docker-logs:
	docker compose logs -f --tail=100

deploy:             ## обновить код на сервере и перезапустить
	git pull && venv/bin/pip install -q -r requirements.txt && sudo systemctl restart shopbot
