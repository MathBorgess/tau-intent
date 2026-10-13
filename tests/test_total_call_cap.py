"""Total-call budget uses real call boundaries, independent of arm tools."""
import asyncio
from pathlib import Path

import httpx
import pytest

from tau_intent.cli import flags_from_args
from tau_intent.fake_provider import FakeHarness, FakeToolStart, FakeTurnEnd
from tau_intent.gate import Veredito
from tau_intent.harness_factory import WireLog, stamping_transport
from tau_intent.supervisor import run_task

DIFF = 'diff --git a/mod.py b/mod.py\n--- a/mod.py\n+++ b/mod.py\n@@ -1,0 +1,2 @@\n+def f():\n+    return 1\n'


class Calls(FakeHarness):
    def __init__(self, events):
        super().__init__()
        self.events = events
        self.calls = 0

    async def prompt(self, prompt):
        for events in self.events:
            self.calls += 1
            for event in events:
                yield event


def execute(tmp_path, arm, events, **kwargs):
    (tmp_path / 'mod.py').write_text('def f():\n    return 1\n')
    harness = Calls(events)
    result = asyncio.run(run_task(tmp_path, flags_from_args(['--arm', arm]), harness=harness,
        diff=DIFF, max_productive_turns=32, max_total_calls=32, **kwargs))
    return harness, result


@pytest.mark.parametrize('arm', ['A', 'B'])
def test_tool_call_32_stops_before_another_call(tmp_path, arm):
    events = [[FakeTurnEnd(tool_results=[{'tool_name': 'bash'}])] for _ in range(40)]
    harness, result = execute(tmp_path, arm, events)
    assert harness.calls == result.telemetry['actual_total_calls'] == len(result.telemetry['turnos']) == 32
    assert result.verdict == 'TETO'
    assert result.telemetry['encerramento'] == 'teto_chamadas'
    assert result.telemetry['total_call_cap_reached']


def test_block_reply_and_last_plain_answer_share_total_budget(tmp_path):
    # Calls1..30 have tools,31 is a blocked final,32 is its plain response.
    events = [[FakeTurnEnd(tool_results=[{'tool_name': 'bash'}])] for _ in range(30)]
    events += [[FakeTurnEnd()], [FakeTurnEnd()], [FakeTurnEnd()]]
    harness, result = execute(tmp_path, 'B', events, gate_fn=lambda *args: Veredito.bloqueia(()))
    assert harness.calls == result.telemetry['actual_total_calls'] == 32
    assert len(harness.follow_ups) == 2  # One budget notice plus one gate reply; none for call33.
    assert result.telemetry['turnos'][-1]['kind'] == 'block'
    assert result.verdict == 'TETO'


def test_final_answer_at_call_32_can_finish_without_call_33(tmp_path):
    events = [[FakeTurnEnd(tool_results=[{'tool_name': 'bash'}])] for _ in range(31)]
    events += [[FakeTurnEnd()], [FakeTurnEnd()]]
    harness, result = execute(tmp_path, 'A', events)
    assert harness.calls == result.telemetry['actual_total_calls'] == 32
    assert result.verdict == 'PASSA'
    assert result.telemetry['total_call_cap_reached']


def test_last_allowed_record_publishes_without_call_33(tmp_path):
    events = [[FakeTurnEnd(tool_results=[{'tool_name': 'bash'}])] for _ in range(31)]
    events += [[FakeToolStart(tool_name='record_intent', args={'file': 'mod.py',
                'why': 'f returns one', 'property': 'result equals one', 'symbol': 'f', 'domain': 'demo'}),
                FakeTurnEnd(tool_results=[{'tool_name': 'record_intent'}])]]
    harness, result = execute(tmp_path, 'B', events)
    assert harness.calls == 32
    assert result.verdict == 'TETO'
    assert result.telemetry['intencoes_publicadas'] > 0


def test_transport_stops_hidden_sdk_retry_before_request_33():
    forwarded = []
    async def request(req):
        forwarded.append(req)
        return httpx.Response(200, json={'ok': True})
    wire = WireLog(stamp={}, max_total_calls=32)
    async def run():
        async with httpx.AsyncClient(transport=stamping_transport(httpx.MockTransport(request), {}, wire)) as client:
            for _ in range(32):
                await client.post('http://local/v1/messages', json={'model': 'fake'})
            with pytest.raises(RuntimeError, match='budget exhausted'):
                await client.post('http://local/v1/messages', json={'model': 'fake'})
    asyncio.run(run())
    assert len(forwarded) == len(wire.bodies) == 32
    assert wire.rejected_over_budget == 1


def test_failed_transport_attempt_consumes_budget():
    wire = WireLog(stamp={}, max_total_calls=1)
    forwarded = []
    async def fail(req):
        forwarded.append(req)
        raise httpx.ConnectError('offline failure', request=req)
    async def run():
        async with httpx.AsyncClient(transport=stamping_transport(httpx.MockTransport(fail), {}, wire)) as client:
            with pytest.raises(httpx.ConnectError):
                await client.post('http://local/v1/messages', json={'model': 'fake'})
            with pytest.raises(RuntimeError, match='budget exhausted'):
                await client.post('http://local/v1/messages', json={'model': 'fake'})
    asyncio.run(run())
    assert wire.request_attempts == len(forwarded) == 1


def test_cli_cap_is_explicit_and_serializes_in_record():
    from tau_intent.bench.cli import build_parser
    from tau_intent.bench.record import mechanism_telemetry
    from tau_intent.bench.cell import validate_assign, CellError
    parser = build_parser()
    assert parser.get_default('max_total_calls') is None
    assert parser.parse_args(['--provider-url', 'http://local', '--model', 'fake', '--taskset', '/tmp/taskset', '--out', '/tmp/out', '--max-total-calls', '32']).max_total_calls == 32
    assign = dict(cell_id='test', mode='bench', arms=['A', 'B'], seed=7, k_max=1, deadline_s=60, max_productive_turns=8)
    validate_assign(assign)
    validate_assign({**assign, 'max_total_calls': 32})
    with pytest.raises(CellError):
        validate_assign({**assign, 'max_total_calls': 0})
    tel = dict(actual_total_calls=32, total_call_cap=32, total_call_count_source='wire_requests', total_call_budget_scope='agent_episode')
    output = mechanism_telemetry(tel, 'TETO', 30, 2)
    assert all(output[key] == value for key, value in tel.items())


def test_declared_cap_disables_sdk_retries_only_for_capped_harness(tmp_path, monkeypatch):
    import tau_intent.harness_factory as factory
    seen = []
    class Stop(Exception):
        pass
    def provider(spec, client, wire, *, max_retries):
        seen.append((max_retries, wire.max_total_calls))
        raise Stop
    monkeypatch.setattr(factory, 'stamped_client', lambda spec: (None, WireLog(stamp={})))
    monkeypatch.setattr(factory, 'build_provider', provider)
    for cap in (None, 32):
        with pytest.raises(Stop):
            factory.build_harness(tmp_path, flags_from_args(['--arm', 'A']), None, max_total_calls=cap)
    assert seen == [(2, None), (0, 32)]
