def test_package_import():
    import nmrpaint

    assert hasattr(nmrpaint, "create_app")