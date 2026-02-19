import os
import sys
import traceback
from pathlib import Path

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

def ensure_project_on_path():
    """
    Ensures 'word_counter_dsc' package can be imported regardless of where tests are run from.
    """
    tests_dir = Path(__file__).resolve().parent
    project_dir = tests_dir.parent                  # .../word_counter_dsc
    repo_root = project_dir.parent                  # parent of word_counter_dsc

    # Add repo root so `import word_counter_dsc...` works everywhere
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

def run_test(name, func):
    try:
        func()
        print(f"[PASS] {name}")
    except Exception:
        print(f"[FAIL] {name}")
        traceback.print_exc()

def main():
    clear_screen()
    ensure_project_on_path()

    print("\n=== RUNNING FULL TEST SUITE ===\n")

    from test_structure import run_structure_tests
    from test_database import run_database_tests
    from test_logic import run_logic_tests
    from test_bot_load import run_bot_tests
    from test_concurrency import run_concurrency_tests
    from test_main_smoke import run_main_smoke_tests

    run_test("Structure", run_structure_tests)
    run_test("Database", run_database_tests)
    run_test("Logic", run_logic_tests)
    run_test("Bot Load", run_bot_tests)
    run_test("Concurrency", run_concurrency_tests)
    run_test("Main Smoke", run_main_smoke_tests)

    print("\n=== TESTING COMPLETE ===\n")

if __name__ == "__main__":
    main()
