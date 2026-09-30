"""encode_batch_members 契约钉点：payload≡encode_batch、members[k]≡encode_newlines(texts[k])[0]。

``pipeline._batch_call`` 消费 ``members[k]`` 直作 ``bare_token_audit`` 基线
（批成员编码只跑一次，与线发字节结构性同源）——契约漂移会让对账基线与
实发字节脱钩，此处钉死防回归。
"""

from texlate.xlat import batch
from texlate.xlat.placeholders import encode_newlines, find_all


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
        # members[k] 须与批内 [k+1] 编号段逐字节同源——_batch_call 的对账前提。
        # ph 成员行形 ``[k] keep: ids | enc``（名单 = find_all 首见序 + ``|``
        # 分隔）；ph-free 成员保持 ``[k] enc`` 单行。
        texts = ["first\none", "second", "third\n\npara", "plain four"]
        payload, members = batch.encode_batch_members(texts)
        lines = payload.split("\n")
        assert len(lines) == len(members)  # 每成员恒一行——编码面无裸换行
        for k, enc in enumerate(members):
            ids = find_all(enc)
            prefix = f"keep: {' '.join(ids)} | " if ids else ""
            assert lines[k] == f"[{k + 1}] {prefix}{enc}"

    def test_keep_prefix_names_member_ph(self) -> None:
        # keep 名单 = find_all 首见序去重——重发 token 只列一次
        payload, _m = batch.encode_batch_members(
            ["see [[CITE_1]] and [[MATH_2]] twice [[CITE_1]]", "plain"]
        )
        assert payload == (
            "[1] keep: [[CITE_1]] [[MATH_2]] | "
            "see [[CITE_1]] and [[MATH_2]] twice [[CITE_1]]\n"
            "[2] plain"
        )

    def test_marker_shaped_member_stays_inline(self) -> None:
        # ``[k]`` 形起头的成员编码留在行中——序号行内嵌 keep 前缀
        # 不把正文拱上行首误锚定（两行式曾整批炸多重集）
        payload, _m = batch.encode_batch_members(["[12] cite head~x", "plain"])
        lines = payload.split("\n")
        assert len(lines) == 2  # noqa: PLR2004 -- 两成员两行即断言义
        assert lines[0].startswith("[1] keep:")
        assert lines[0].index("[12]") > 0  # 字面 [12] 在行中非行首——不误锚定
        assert batch.parse_batch_response(payload, 2) is not None

    def test_empty(self) -> None:
        assert batch.encode_batch_members([]) == ("", [])
