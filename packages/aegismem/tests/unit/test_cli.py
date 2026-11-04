"""CLI argument handling and dispatch (no live server)."""
from apps.cli import build_parser, run


class FakeClient:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*a, **kw):
            self.calls.append((name, a, kw))
            return {"ok": name}
        return call


def test_commands_dispatch_to_sdk():
    p, c = build_parser(), FakeClient()
    run(p.parse_args(["ingest", "Alice likes FAISS", "--user", "alice", "--type", "fact"]), c)
    run(p.parse_args(["recall", "faiss", "--user", "alice", "--top-k", "3"]), c)
    run(p.parse_args(["feedback", "r1", "--user", "alice", "--used", "m1", "m2"]), c)
    run(p.parse_args(["correct", "m1", "--user", "alice", "--kind", "outdated", "--text", "now Rust"]), c)
    run(p.parse_args(["forget", "m1", "--user", "alice"]), c)
    names = [n for n, _, _ in c.calls]
    assert names == ["ingest", "retrieve", "feedback", "correct", "forget"]
    assert c.calls[2][1] == ("r1", "alice", ["m1", "m2"])
    assert c.calls[3][2]["corrected_text"] == "now Rust"
