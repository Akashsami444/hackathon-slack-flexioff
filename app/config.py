import os

class Settings:
    def __init__(self):
        # Required settings
        self.SLACK_BOT_TOKEN = self._get("SLACK_BOT_TOKEN")
        self.SLACK_SIGNING_SECRET = self._get("SLACK_SIGNING_SECRET")
        self.OPENAI_API_KEY = self._get("OPENAI_API_KEY")
        # self.MANAGER_USER_ID = self._get("MANAGER_USER_ID")
        self.EMPLOYEE_GCAL_EMAIL = self._get("EMPLOYEE_GCAL_EMAIL")
    
    def _get(self, name):
        value = os.environ.get(name)
        if value is None:
            raise RuntimeError(f"Missing required environment variable: {name}")
        return value

# Create a module-level singleton instance to import anywhere
settings = Settings()