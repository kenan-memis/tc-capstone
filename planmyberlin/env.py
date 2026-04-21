"""Load `.env` once for local development.

Cloud Run and other hosts inject secrets as process environment variables;
`load_dotenv` does not override existing variables.
"""

from dotenv import load_dotenv

load_dotenv()

from planmyberlin.observability import configure_logging_from_settings

configure_logging_from_settings()
