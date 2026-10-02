from scripts.sync_postman_collection import sync


def test_postman_collection_covers_every_route():
    """
    Fails with a clear message if an endpoint was added/removed without
    running `python scripts/sync_postman_collection.py` -- run that script
    (it edits postman/*.json in place) and re-run the tests.
    """
    would_change = sync(check_only=True)
    assert not would_change, (
        "postman/SmartGrowAI.postman_collection.json is missing one or more endpoints. "
        "Run `python scripts/sync_postman_collection.py` and commit the result."
    )
