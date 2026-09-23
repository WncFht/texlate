"""M2 canon() 验收：30 形态表全收 + 44 对抗探针拒收面 + 壳不变式。

规格 tmp/ux-research-20260922/arxiv-id-canon-spec.md + misc-pack 实现文档
§M2；对抗面实测表 exp/ms-urlnorm/rerun_adv.txt（6 回归形必收、8 过收形
必拒、spoof/``..``/unicode/v0 必拒）。
"""

from __future__ import annotations

import pytest

from texlate.arxiv.fetch import (
    CanonError,
    canon,
    normalize_arxiv_id,
    req_base_ver,
    try_canon,
    valid_id,
)

# ------------------------------------------------------------ 必收面

#: (raw, base, version)——覆盖 spec §1 输入面 + rerun_adv 6 回归形 +
#: DOI 四形态 + 镜像白名单臂 + 旧形 class 剥壳 + safe_id 回流。
ACCEPT = [
    ("2301.12345", "2301.12345", None),
    ("  2301.12345  ", "2301.12345", None),
    ("2301.12345v2", "2301.12345", 2),
    ("2301.12345V03", "2301.12345", 3),  # V→v + 导零剥
    ("arXiv:2301.12345", "2301.12345", None),
    ("ARXIV:2301.12345", "2301.12345", None),
    ("arXiv : 2301.12345", "2301.12345", None),
    ("arxiv.2301.12345", "2301.12345", None),
    ("oai:arXiv.org:2301.12345", "2301.12345", None),
    ("https://arxiv.org/abs/2301.12345", "2301.12345", None),
    ("http://arxiv.org/pdf/2301.12345", "2301.12345", None),
    ("arxiv.org/abs/2301.12345", "2301.12345", None),  # 裸域无 scheme
    ("https://export.arxiv.org/abs/2301.12345", "2301.12345", None),
    ("https://arxiv.org/abs/2301.12345?x=?y#z", "2301.12345", None),
    ("https://arxiv.org/pdf/2301.12345.PDF", "2301.12345", None),
    # rerun_adv 6 回归形（extended 臂曾丢——必须收）
    ("2301.12345.pdf", "2301.12345", None),
    ("2301.12345v2.pdf", "2301.12345", 2),
    ("arXiv:2301.12345.pdf", "2301.12345", None),
    ("2301.12345/", "2301.12345", None),
    ("/2301.12345", "2301.12345", None),
    ("hep-th/9901001.pdf", "hep-th/9901001", None),
    # 扩展名链 + 尾注
    ("2301.12345.tar.gz", "2301.12345", None),
    ("2301.12345 [cs.CL]", "2301.12345", None),
    ("2301.12345 [cs.CL].pdf", "2301.12345", None),
    # DOI 四形态 + 链式前缀 + 版本钉
    ("doi:10.48550/arXiv.2301.12345", "2301.12345", None),
    ("doi:10.48550/arXiv.2301.12345v2", "2301.12345", 2),
    ("https://doi.org/10.48550/arXiv.2301.12345", "2301.12345", None),
    ("https://dx.doi.org/10.48550/arXiv.2301.12345", "2301.12345", None),
    ("10.48550/arXiv.2301.12345", "2301.12345", None),
    ("10.48550/arXiv.cs.AI/0001001", "cs/0001001", None),  # 旧形 DOI 内嵌
    # ar5iv/alphaXiv 显式 host 白名单（须 scheme，动词限 abs|pdf|html）
    ("https://ar5iv.org/abs/2301.12345", "2301.12345", None),
    ("https://ar5iv.labs.arxiv.org/html/2301.12345", "2301.12345", None),
    ("https://alphaxiv.org/abs/2301.12345", "2301.12345", None),
    ("https://www.alphaxiv.org/pdf/2301.12345", "2301.12345", None),
    # 旧形：裸/class 剥壳/archive 小写/safe_id 回流/URL 形
    ("hep-th/9901001", "hep-th/9901001", None),
    ("cond-mat.mes-hall/0501234", "cond-mat/0501234", None),
    ("https://arxiv.org/abs/math.GT/0309136", "math/0309136", None),
    ("math.GT/0309136v2", "math/0309136", 2),
    ("hep-th--9901001", "hep-th/9901001", None),  # safe_id ``--`` 回流
    ("https://arxiv.org/abs/astro-ph/0001001", "astro-ph/0001001", None),
    ("HEP-TH/9901001", "hep-th/9901001", None),  # archive 小写化
    # 时代窗边界（新形窗 0704–9106；seq 位数不做时代闸）
    ("1412.6980", "1412.6980", None),
    ("0704.0001", "0704.0001", None),
    ("9106.99999", "9106.99999", None),
]

#: 必拒面（rerun_adv 过收 8 + spoof 3 + canon_test FAIL 族 + spec 不收清单）
REJECT = [
    # 非 http(s) scheme / 镜像域名 / 未实证动词 / 端口 / 双斜杠
    "ftp://arxiv.org/abs/2301.12345",
    "javascript://arxiv.org/abs/2301.12345",
    "https://lanl.gov/abs/2301.12345",
    "https://www.lanl.gov/abs/2301.12345",
    "https://xxx.lanl.gov/abs/2301.12345",
    "ar5iv.org/abs/2301.12345",  # 镜像臂缺 scheme
    "https://alphaxiv.org/overview/2301.12345",  # 未实证动词
    "https://arxiv.org:8080/abs/2301.12345",
    "https://arxiv.org//abs//2301.12345",
    # 寄生/伪域三 spoof
    "https://arxiv.org./abs/2301.12345",  # FQDN 尾点
    "https://arxiv.org.evil.com/abs/2301.12345",
    "https://notarxiv.org/abs/2301.12345",
    "https://arxiv.org@evil.com/abs/2301.12345",
    "https://www.doi.org/10.48550/arXiv.2301.12345",  # www.doi.org 不收
    "doi : 10.48550/arXiv.2301.12345",  # 冒号前空格
    # 形残/动词白名单外
    "https://arxiv.org/abs/2301.12345/extra",
    "https://arxiv.org/list/2301.12345",
    "https://arxiv.org/abs/",
    "https://arxiv.org/",
    "arxiv.org",
    "abs/2301.12345",
    "https://arxiv.org/abs/2301.12345v",  # v 无数字
    "2301.12345v9999",  # 版本 >3 位
    "2301.12345v2junk",
    "2301.12345v0",  # v0 非法版本
    "arXiv:2301.00001v2]",  # 括号残件
    "2301.00001 extra",  # 散文尾
    "not-an-id",
    "arXiv preprint 2301.12345",  # 散文形
    "2007.12.3456",  # 旧历日期形
    "",
    "   ",
    # MM/era 语义闸（spec §3：不可能 id 本地拒）
    "1234.5678",  # mm=34
    "0000.0000",  # mm=00
    "9913.00001",  # mm=13
    "2300.00001",  # mm=00
    "0601.00001",  # 新形撞旧时代窗
    "9912.00001",  # 新形 9912 不可能存在（deviation 定案）
    "9912.3456",
    "hep-th/0801001",  # 旧形撞新时代窗
    "hep-th/9913001",  # 旧形 mm=13
    # 逃逸/unicode/毒件
    "2301.00001/../2301.00002",
    "../../etc/passwd",
    "astro-ph--0104007.bak-mock",  # unfold 后仍非 id
    "２３０１.１２３４５",  # unicode 全角数字
]


class TestCanonAccept:
    @pytest.mark.parametrize(("raw", "base", "ver"), ACCEPT)
    def test_accept(self, raw: str, base: str, ver: int | None) -> None:
        c = canon(raw)
        assert c.base == base
        assert c.version == ver

    @pytest.mark.parametrize("raw", [a[0] for a in ACCEPT])
    def test_idempotent(self, raw: str) -> None:
        """``canon(str(canon(x))) == canon(x)``——规范形回喂幂等。"""
        c = canon(raw)
        assert canon(str(c)) == c

    def test_scheme_flag(self) -> None:
        assert canon("2301.12345").scheme == "new"
        assert canon("hep-th/9901001").scheme == "old"

    def test_safe_roundtrip(self) -> None:
        """``canon(s.safe())`` 回原 canon——``--``↔``/`` 存储拼写两形同键。"""
        c = canon("hep-th/9901001")
        assert c.safe() == "hep-th--9901001"
        assert canon(c.safe()) == c

    def test_strict_era_off(self) -> None:
        """``strict_era=False`` 放行跨时代形（MM 闸仍在）。"""
        assert canon("9912.00001", strict_era=False).base == "9912.00001"
        assert (
            canon("hep-th/0801001", strict_era=False).base == "hep-th/0801001"
        )


class TestCanonReject:
    @pytest.mark.parametrize("raw", REJECT)
    def test_reject(self, raw: str) -> None:
        assert try_canon(raw) is None
        with pytest.raises(CanonError):
            canon(raw)

    @pytest.mark.parametrize(
        ("raw", "reason"),
        [
            ("9913.00001", "bad_month"),
            ("1234.5678", "bad_month"),
            ("hep-th/9913001", "bad_month"),
            ("0601.00001", "bad_era"),
            ("9912.00001", "bad_era"),
            ("hep-th/0801001", "bad_era"),
            ("2301.12345v0", "bad_version"),
            ("2301.00001/../2301.00002", "unsafe"),
            ("../../etc/passwd", "unsafe"),
            ("not-an-id", "bad_shape"),
            ("", "bad_shape"),
        ],
    )
    def test_reason(self, raw: str, reason: str) -> None:
        """``CanonError.reason`` 五值枚举——服务端 400 detail 派生源。"""
        with pytest.raises(CanonError, match=reason) as ei:
            canon(raw)
        assert ei.value.reason == reason


# ------------------------------------------------------------ 薄壳不变式


class TestShells:
    def test_normalize_success(self) -> None:
        assert normalize_arxiv_id("arXiv:math.GT/0309136v2") == (
            "math/0309136",
            2,
        )
        assert normalize_arxiv_id("1412.6980") == ("1412.6980", None)

    def test_normalize_never_raises(self) -> None:
        """拒收输入 → ``(剥离剩件, None)``——旧契约「任意输入不抛」保留。"""
        assert normalize_arxiv_id("1412.6980v0") == ("1412.6980v0", None)
        assert normalize_arxiv_id("arxiv.org/abs/") == ("", None)
        assert normalize_arxiv_id("../../etc/passwd") == (
            "../../etc/passwd",
            None,
        )
        base, ver = normalize_arxiv_id("https://arxiv.org@evil.com/abs/1")
        assert ver is None
        assert not valid_id(base)

    def test_valid_id_canonical_only(self) -> None:
        """``valid_id`` 收窄为规范形：canon 可收输入 ≠ 合法 base。"""
        assert valid_id("2301.12345")
        assert valid_id("hep-th/9901001")
        assert not valid_id("math.GT/0309136")  # classful 非规范形
        assert not valid_id("HEP-TH/9901001")
        assert not valid_id("2301.12345v2")  # 钉版串非 base
        assert not valid_id("hep-th--9901001")  # safe 拼写非 base
        assert not valid_id("a/../b")
        assert not valid_id("")

    def test_req_base_ver(self) -> None:
        assert req_base_ver("arXiv:2301.12345v2") == ("2301.12345", 2)
        assert req_base_ver("2301.12345", 3) == ("2301.12345", 3)  # 实参胜
        assert req_base_ver("2301.12345v2", 3) == ("2301.12345", 3)
        with pytest.raises(ValueError, match="bad_era"):
            req_base_ver("9912.00001")
        with pytest.raises(ValueError, match="bad_version"):
            req_base_ver("2301.12345", 0)
