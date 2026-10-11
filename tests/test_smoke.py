def test_package_imports():
    import recommender
    from recommender import config, schemas  # noqa: F401

    assert recommender.__doc__
