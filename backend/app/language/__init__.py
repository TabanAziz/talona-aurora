"""Messages in the language of the crew. A helper package: it imports no area and reaches the model only through
app.core.llm.complete_json."""
from .translate import ENGLISH, localize, localize_reply, looks_english

__all__ = ["ENGLISH", "localize", "localize_reply", "looks_english"]
