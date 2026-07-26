from nmrpaint.resource_manager import (
    list_resource_names,
    read_resource_text,
    resource_directory_exists,
)


def test_elements_directories_exist():
    assert resource_directory_exists("elements", "pulse")
    assert resource_directory_exists("elements", "shaped")
    assert resource_directory_exists("elements", "grad")
    assert resource_directory_exists("elements", "block")
    assert resource_directory_exists("elements", "flag")


def test_pulse_resources_are_available():
    pulse_files = list_resource_names(
        "elements",
        "pulse",
        suffix=".txt",
    )

    assert pulse_files


def test_delay_definition_can_be_read():
    content = read_resource_text("defs", "delay_def.txt")

    assert isinstance(content, str)
    assert content.strip()


def test_definition_files_are_available():
    expected_files = {
        "pulse_def.txt",
        "power_def.txt",
        "delay_def.txt",
        "cnst_def.txt",
        "loops_def.txt",
    }

    available = set(
        list_resource_names(
            "defs",
            suffix=".txt",
        )
    )

    assert expected_files.issubset(available)


from nmrpaint.resource_manager import (
    list_resource_names,
    resource_directory_exists,
)


ELEMENT_TYPES = [
    "pulse",
    "shaped",
    "grad",
    "block",
    "flag",
]


def test_all_element_categories_contain_files():
    for element_type in ELEMENT_TYPES:
        assert resource_directory_exists("elements", element_type)

        files = list_resource_names(
            "elements",
            element_type,
            suffix=".txt",
        )

        assert files, f"No element files found for {element_type}"