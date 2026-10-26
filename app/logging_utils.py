"""Keep diagnostics useful without exposing credentials in request URLs/errors."""
import logging
import os
import re


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        for name in ('TOKEN', 'TELEGRAM_BOT_TOKEN', 'MAX_BOT_TOKEN', 'OCR_SPACE_API_KEY', 'DEEPSEEK_API_KEY', 'POSTGRES_PASSWORD'):
            value = os.environ.get(name)
            if value:
                text = text.replace(value, '[REDACTED]')
        text = re.sub(r'\b\d{6,}:[A-Za-z0-9_-]+', '[REDACTED]', text)
        return re.sub(r'(postgres(?:ql)?://[^: /]+:)[^@\s]+(@)', r'\1[REDACTED]\2', text)
