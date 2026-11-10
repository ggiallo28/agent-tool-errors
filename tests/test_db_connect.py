"""connect(role): backend choice and role validation. Both backends are replaced by fakes."""
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opsmem import db


class Fake:
    def __init__(self, role):
        self.role = role


@pytest.fixture
def fakes(monkeypatch):
    monkeypatch.setattr(db, "LocalBackend", type("FakeLocal", (Fake,), {}))
    monkeypatch.setattr(db, "AuroraBackend", type("FakeAurora", (Fake,), {}))


# Feature: catalog-schema, Property 1: Backend selection follows OPSMEM_LOCAL_PG
@settings(max_examples=100, deadline=None)
@given(st.one_of(st.none(), st.just(""), st.text(alphabet=st.characters(blacklist_characters="\x00", blacklist_categories=("Cs",)), min_size=1, max_size=15)), st.sampled_from(db.ROLES))
def test_property_backend_selection(value, role):
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(db, "LocalBackend", type("FakeLocal", (Fake,), {}))
        mp.setattr(db, "AuroraBackend", type("FakeAurora", (Fake,), {}))
        if value is None:
            mp.delenv("OPSMEM_LOCAL_PG", raising=False)
        else:
            mp.setenv("OPSMEM_LOCAL_PG", value)
        backend = db.connect(role)
        assert backend.role == role
        assert type(backend).__name__ == ("FakeLocal" if value else "FakeAurora")
    finally:
        mp.undo()


# Feature: catalog-schema, Property 2: Invalid roles are rejected before any connection
@settings(max_examples=100)
@given(st.one_of(st.none(), st.integers(), st.floats(allow_nan=False), st.binary(max_size=5),
                 st.text(max_size=12).filter(lambda s: s not in db.ROLES),
                 st.sampled_from(["Admin", "ADMIN", "approver ", " agent_writer", ""])))
def test_property_invalid_roles(role):
    mp = pytest.MonkeyPatch()
    created = []
    try:
        mp.setattr(db, "LocalBackend", lambda r: created.append(r))
        mp.setattr(db, "AuroraBackend", lambda r: created.append(r))
        with pytest.raises(ValueError) as err:
            db.connect(role)
        assert repr(role) in str(err.value)
        assert created == []
    finally:
        mp.undo()


def test_a_str_subclass_is_not_a_role(fakes):
    class Role(str):
        pass

    with pytest.raises(ValueError):
        db.connect(Role("admin"))
