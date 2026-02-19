from pathlib import Path

def run_structure_tests():
    base = Path(__file__).resolve().parent.parent  # .../word_counter_dsc

    required = [
    "main.py",
    "config.py",
    "database.py",
    "utils.py",
    "requirements.txt",
    "cogs/__init__.py",
    "cogs/tracker.py",
    "cogs/search.py",
    "cogs/keyword.py",
    "cogs/stopwords.py",
    "cogs/help_cmd.py",
    "cogs/medals.py",
    "cogs/profile.py",
    "ui/theme.py",
    "ui/pagination.py",
    ]


    missing = [p for p in required if not (base / p).exists()]
    if missing:
        raise FileNotFoundError("Missing required files:\n" + "\n".join(missing))
