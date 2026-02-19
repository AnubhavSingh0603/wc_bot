def run_logic_tests():
    from word_counter_dsc.utils import tokenize

    # Basic tokenization
    words = tokenize("Hello world! Hello again.")
    if words != ["hello", "world", "hello", "again"]:
        raise Exception(f"Tokenizer mismatch. Got: {words}")

    # Edge: empty input
    if tokenize("") != []:
        raise Exception("Tokenizer should return [] for empty string")

    # Edge: punctuation only
    if tokenize("!!! ... ???") != []:
        raise Exception("Tokenizer should return [] for punctuation-only input")

    # Edge: contractions & digits
    w = tokenize("I'm 19, it's fine. user123")
    # tokenize() keeps apostrophes per regex; expected tokens include i'm and it's
    if "i'm" not in w or "it's" not in w or "19" not in w or "user123" not in w:
        raise Exception(f"Tokenizer edge case failed. Got: {w}")
