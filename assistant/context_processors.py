from assistant.llm import is_configured


def assistant(request):
    return {"assistant_enabled": is_configured()}
