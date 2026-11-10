"""check_config: required variables at startup. Offline."""
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opsmem import db

names = st.lists(st.from_regex(r"[A-Z][A-Z0-9_]{2,10}", fullmatch=True), max_size=6, unique=True)
state = st.sampled_from(["absent", "empty", "set"])


def set_env(monkeypatch, env):
    for key, kind in env.items():
        monkeypatch.delenv(key, raising=False)
        if kind != "absent":
            monkeypatch.setenv(key, "" if kind == "empty" else "x")


# Feature: catalog-schema, Property 8: Configuration check
@settings(max_examples=100)
@given(names, st.data())
def test_property_check_config(names, data):
    mp = pytest.MonkeyPatch()
    try:
        mp.delenv("OPSMEM_LOCAL_PG", raising=False)
        env = {n: data.draw(state) for n in names}
        set_env(mp, env)
        missing = [n for n in names if env[n] != "set"]
        import io, sys
        buf = io.StringIO()
        mp.setattr(sys, "stderr", buf)
        if not missing:
            db.check_config(names)
            assert buf.getvalue() == ""
        else:
            with pytest.raises(SystemExit) as stop:
                db.check_config(names)
            assert stop.value.code == 1
            assert buf.getvalue() == "Configuration error, agent not started. Missing: " + ", ".join(missing) + "\n"
    finally:
        mp.undo()


# Feature: catalog-schema, Property 9: Local mode replaces the required list
@settings(max_examples=100)
@given(names, state)
def test_property_local_mode_required_list(names, region):
    mp = pytest.MonkeyPatch()
    try:
        mp.setenv("OPSMEM_LOCAL_PG", "localhost:55432")
        set_env(mp, {"AWS_REGION": region})
        for n in names:
            mp.delenv(n, raising=False)
        import io, sys
        buf = io.StringIO()
        mp.setattr(sys, "stderr", buf)
        if region == "set":
            db.check_config(names)
            assert buf.getvalue() == ""
        else:
            with pytest.raises(SystemExit):
                db.check_config(names)
            assert buf.getvalue() == "Configuration error, agent not started. Missing: AWS_REGION\n"
    finally:
        mp.undo()


def test_empty_required_list_returns(monkeypatch):
    monkeypatch.delenv("OPSMEM_LOCAL_PG", raising=False)
    db.check_config([])
