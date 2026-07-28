from pathlib import Path

from nmrpaint.exporters import (
    normalize_output_filename,
    save_text_local,
    write_text_file,
)


def test_empty_title_uses_default_filename():
    assert normalize_output_filename("") == "pulse_program"
    assert normalize_output_filename(None) == "pulse_program"


def test_invalid_filename_characters_are_replaced():
    filename = normalize_output_filename(
        'test:/sequence*?"<>|'
    )

    assert filename == "test__sequence______"


def test_windows_reserved_filename_is_prefixed():
    assert normalize_output_filename("CON") == "_CON"
    assert normalize_output_filename("COM1.txt") == "_COM1.txt"


def test_write_text_file_uses_explicit_path(
    tmp_path: Path,
):
    output_path = tmp_path / "explicit_program"

    result = write_text_file(
        output_path,
        "pulse program\n",
    )

    assert result == output_path
    assert result.exists()
    assert result.read_text(encoding="utf-8") == "pulse program\n"


def test_save_text_local_uses_output_directory(
    tmp_path: Path,
):
    result = save_text_local(
        content="pulse program\n",
        filename="test_program",
        output_dir=tmp_path,
    )

    assert result == tmp_path / "test_program"
    assert result.exists()
    assert result.read_text(encoding="utf-8") == "pulse program\n"
