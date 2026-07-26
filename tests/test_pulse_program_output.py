from pathlib import Path

from nmrpaint import app


def test_build_pulse_program_text_returns_text():
    text = app.build_pulse_program_text()

    assert isinstance(text, str)
    assert "#include <Avance.incl>" in text
    assert "1 ze" in text
    assert "go=2 ph31" in text
    assert "exit" in text
    assert "Generated using NMRpaintv1" in text


def test_save_pulse_program(tmp_path: Path):
    content = "test pulse program\n"
    output_path = tmp_path / "test_program"

    result = app.save_pulse_program(
        filename=output_path,
        content=content,
    )

    assert result == output_path
    assert output_path.exists()
    assert output_path.read_text(encoding="utf-8") == content


def test_generate_pulse_program_creates_file(tmp_path: Path):
    output_path = tmp_path / "generated_program"

    result = app.generate_pulse_program(output_path)

    assert result == output_path
    assert output_path.exists()

    content = output_path.read_text(encoding="utf-8")

    assert "#include <Avance.incl>" in content
    assert "go=2 ph31" in content
    assert "exit" in content