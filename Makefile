NGROK_URL := https://reviving-tinsmith-fried.ngrok-free.dev

.PHONY: run

run:
	@trap 'kill 0' INT TERM EXIT; \
	uv run main.py & \
	ngrok http 8000 --url $(NGROK_URL) --log=stdout & \
	wait