.PHONY: venv install run clean

# ----- ENVIRONMENT -----
export SLACK_BOT_TOKEN=xoxb-your-token
export SLACK_SIGNING_SECRET=your-signing-secret
export OPENAI_API_KEY=sk-your-key
export EMPLOYEE_GCAL_EMAIL=employee@email.com
# -----------------------

venv:
	python3 -m venv .venv

install: venv
	. .venv/bin/activate && pip install --upgrade pip && pip install -r requirements.txt

run:
	. .venv/bin/activate && uvicorn app.main:app --reload

update-requirements:
	. .venv/bin/activate && pip freeze > requirements.txt

clean:
	rm -rf .venv __pycache__ .pytest_cache