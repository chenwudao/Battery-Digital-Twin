from battery_dt.storage.db import Database


def test_database_persistent_batch_and_dedupe(tmp_path) -> None:
    db = Database(tmp_path / "test.db")
    db.init()
    db.open_persistent()
    run_id = db.create_run("2026-11-08T10:00:00Z", {"test": True})
    expected = [True, False, True]
    for seq, should_insert in zip((1, 1, 2), expected):
        inserted = db.insert_measurement(
            asset_id="pack01",
            variable="voltage_V",
            value=48.0,
            unit="V",
            ts_source=f"2026-11-08T10:00:0{seq}.000Z",
            ts_ingest=f"2026-11-08T10:00:0{seq}.100Z",
            seq=seq,
            quality="good",
            run_id=run_id,
        )
        assert inserted is should_insert
    db.commit()
    db.close()
    series = db.get_series("voltage_V", "pack01")
    assert len(series) == 2
    assert db.counts()["measurements"] == 2
