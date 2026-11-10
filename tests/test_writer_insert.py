"""The insert of a proposal and the reply for a saved draft."""
from hypothesis import given, settings
from hypothesis import strategies as st

from opsmem.writer import INSERT_SQL, RunContext, make_tools
from tests.writer_fakes import FakeDatabase

text = st.text(min_size=1)


# Feature: writer-agent, Property 6: A saved draft is answered and inserted as given
@settings(max_examples=100, deadline=None)
@given(request_id=text, service_id=text, signal_name=text, signal_type=text, source_field=text, unit=text,
       sample_seconds=text)
def test_property_saved_draft(request_id, service_id, signal_name, signal_type, source_field, unit,
                              sample_seconds):
    fake = FakeDatabase()
    ctx = RunContext("run-9", "install-07", "model-y", "raw", fake)
    propose, _ = make_tools(ctx)
    given_args = dict(request_id=request_id, service_id=service_id, signal_name=signal_name,
                      signal_type=signal_type, source_field=source_field, unit=unit,
                      sample_seconds=sample_seconds)
    reply = propose(**given_args)
    assert reply == (f"Saved as draft: {signal_name} <- {source_field} ({unit}, every {sample_seconds} s). "
                     "A person will review it.")
    [(sql, params)] = fake.statements
    assert sql == INSERT_SQL
    assert "CAST(:sample_seconds AS integer)" in sql
    assert params == {"run_id": "run-9", "installation_id": "install-07", "model_id": "model-y", **given_args}
    assert isinstance(params["sample_seconds"], str)
