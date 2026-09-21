"""encode_batch_members 契约钉点：payload≡encode_batch、members[k]≡encode_newlines(texts[k])[0]。

``pipeline._batch_call`` 消费 ``members[k]`` 直作 ``bare_token_audit`` 基线
（批成员编码只跑一次，与线发字节结构性同源）——契约漂移会让对账基线与
实发字节脱钩，此处钉死防回归。
"""

from texlate.xlat import batch
from texlate.xlat.placeholders import encode_newlines


class TestEncodeBatchMembers:
    def test_payload_matches_encode_batch(self) -> None:
        texts = ["hello world", "second\nline", "[[MATH_1]] only", ""]
        payload, _members = batch.encode_batch_members(texts)
        assert payload == batch.encode_batch(texts)

    def test_members_match_encode_newlines(self) -> None:
        texts = ["alpha\nbeta", "x~y  z", "para one\n\npara two"]
        _payload, members = batch.encode_batch_members(texts)
        assert members == [encode_newlines(t)[0] for t in texts]

    def test_member_index_alignment(self) -> None:
        # members[k] 须与批内 [k+1] 编号段逐字节同源——_batch_call 的对账前提
        texts = ["first\none", "second", "third\n\npara"]
        payload, members = batch.encode_batch_members(texts)
        lines = payload.split("\n")
        for k, enc in enumerate(members):
            assert lines[k] == f"[{k + 1}] {enc}"

    def test_empty(self) -> None:
        assert batch.encode_batch_members([]) == ("", [])
