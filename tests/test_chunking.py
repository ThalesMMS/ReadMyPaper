from readmypaper.services.text_cleaner import ScientificTextCleaner
from readmypaper.types import ProcessingOptions


def test_chunking_respects_limit() -> None:
    cleaner = ScientificTextCleaner(ProcessingOptions(chunk_max_chars=80))
    text = (
        "This is the first sentence of a long scientific paragraph. "
        "This is the second sentence with more detail about the experiment. "
        "This is the third sentence that should be split into a new chunk."
    )

    chunks = cleaner.split_text(text)

    assert len(chunks) >= 2
    assert all(len(chunk) <= 80 for chunk in chunks)
