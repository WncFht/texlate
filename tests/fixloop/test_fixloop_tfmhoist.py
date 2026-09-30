r"""tfmhoist 车道 —— 驱动层 ``Unable to find TFM file "X"`` 签名接线钉。

机理 (tfmcen 普查 2026-09-20, 13 格全中): e-print 自带私有 ``.tfm`` 驻
子目录 (``assets/optimistic.tfm`` / ``NVIDIA-Sans-Font-TTF/NVIDIASans_It.tfm``
/ ``seed/bytesans.tfm`` / ``template/assets/tfss.tfm``) —— TeX 侧经路径
限定名可解, xdvipdfmx 按 ``\pdfmapline`` 裸名走 TFMFONTS 只认 compile cwd
扁平位 → ``xdvipdfmx:fatal:`` (xelatex, SIGPIPE rc=141) / ``error:``
(tectonic, 2408.00714 实证) 双形。签名只在 TeX 侧错清完、.log 零 ``!``
时经 ``_report_of`` stdout_tail 归一成 ``! xdvipdfmx:fatal: …`` /
``! Unable to find TFM file …`` 落 head 段。

接线: 新 head 条目归 ``missing_tfm`` (非新类) —— ``install_tfm`` (20,
payload_required) 先尝 CTAN 可解名, 私有名 filemap 必 miss benign-decline
→ ``driver_tfm_hoist`` (21) 同轮接住, 同目录 ``*.tfm`` 全量 hoist 到
``mp.parent``。

known_gap (不修, 钉档): hoist 目标 ``mp.parent`` —— main_rel 在子目录
时 tfm 落 ``sub/`` 而 compile cwd 若仍在根则仍不可达; 13 格 main 全在
树根零实证。
"""

from functools import lru_cache
from pathlib import Path

from _fixloopkit import MockEngine, make_proj

from texlate.compile.fixloop import Ruleset, builtins, fixloop, load_ruleset
from texlate.compile.fixloop.engine import LoopCtx
from texlate.compile.logparse import parse_text


@lru_cache(maxsize=1)
def _rs() -> Ruleset:
    """ruleset 首用时加载——收集期不 IO。"""
    return load_ruleset()


CLEAN_LOG = "This is pdfTeX\nOutput written on main.pdf (1 page).\n"

# ── rep 层两形 (_report_of stdout_tail 归一后的 ! 行) ──
_XELATEX_TFM_ERR = '! xdvipdfmx:fatal: Unable to find TFM file "optimistic".\n'
_TECTONIC_TFM_ERR = '! Unable to find TFM file "optimistic".\n'
# ── 真实 stdout_tail 原形 (xelatex SIGPIPE 截杀面，.log 干净) ──
_XDVIPDFMX_TAIL = 'xdvipdfmx:fatal: Unable to find TFM file "optimistic".\n'


def test_missing_tfm_taxonomy_both_phrasings() -> None:
    """两 phrasing 同归 missing_tfm|optimistic (引号内裸名无 .tfm 缀)。"""
    assert _rs().taxonomy.classify(parse_text(_XELATEX_TFM_ERR)) == (
        "missing_tfm",
        "optimistic",
    )
    assert _rs().taxonomy.classify(parse_text(_TECTONIC_TFM_ERR)) == (
        "missing_tfm",
        "optimistic",
    )


def test_missing_tfm_taxonomy_nvidia_name() -> None:
    r"""下划线+大小写混合名全抓 (NVIDIASans_It —— ``[\w.-]`` 不截断)。"""
    log = '! xdvipdfmx:fatal: Unable to find TFM file "NVIDIASans_It".\n'
    assert _rs().taxonomy.classify(parse_text(log)) == (
        "missing_tfm",
        "NVIDIASans_It",
    )


def test_driver_tfm_hoist_rule_shape() -> None:
    """臂形态钉：loop 相 order>install_tfm, payload_required, builtin_transform。"""
    rules = {r.id: r for r in _rs().rules}
    install = rules["install_tfm"]
    arm = rules["driver_tfm_hoist"]
    assert arm.phase == "loop"
    assert arm.order > install.order  # CTAN 真装先尝，私有名 decline 同轮接住
    assert arm.when == {"category": "missing_tfm", "payload_required": True}
    assert arm.action["kind"] == "builtin_transform"
    assert arm.action["function"] == "driver_tfm_hoist"


def test_driver_tfm_hoist_e2e(tmp_path: Path) -> None:
    """install_tfm decline → 同轮 hoist 接住：子目录 ``*.tfm`` 全量提扁平位。"""
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "optimistic.tfm").write_bytes(b"tfm-a")
    (assets / "optimistic_bold.tfm").write_bytes(b"tfm-b")
    eng = MockEngine(
        [
            {
                "log": CLEAN_LOG,  # TeX 侧干净 → stdout_tail 归一落 rep
                "tail": _XDVIPDFMX_TAIL,
                "rc": 141,
                "killed_signal": 13,
            },
            {"log": CLEAN_LOG, "pdf": True},
        ],
        installable=set(),  # 私有名 CTAN 无解 → install_tfm benign-decline
    )
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "clean"
    assert cell["rounds"][0]["category"] == "missing_tfm"
    assert cell["rounds"][0]["payload"] == "optimistic"
    # install_tfm(order 20) 先尝 → decline; hoist(order 21) 同轮接住
    assert "optimistic.tfm" in eng.install_calls
    assert any(a["rule"] == "driver_tfm_hoist" for a in cell["actions"])
    assert (tmp_path / "optimistic.tfm").is_file()
    assert (tmp_path / "optimistic_bold.tfm").is_file()  # 同目录全量 hoist


def test_driver_tfm_hoist_ctan_resolvable_stays_install(tmp_path: Path) -> None:
    """CTAN 可解名仍走 install_tfm —— hoist 不抢真装路由。"""
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "optimistic.tfm").write_bytes(b"tfm-a")
    eng = MockEngine(
        [
            {
                "log": CLEAN_LOG,
                "tail": _XDVIPDFMX_TAIL,
                "killed_signal": 13,
            },
            {"log": CLEAN_LOG, "pdf": True},
        ],
        installable={"optimistic.tfm"},
    )
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "clean"
    assert any(a["rule"] == "install_tfm" for a in cell["actions"])
    assert not any(a["rule"] == "driver_tfm_hoist" for a in cell["actions"])
    assert not (tmp_path / "optimistic.tfm").exists()  # 真装路径不 hoist


def test_driver_tfm_hoist_no_payload_decline(tmp_path: Path) -> None:
    """payload=None → builtin 恒 decline unsafe name (payload_required 双闸)。"""
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    ok, note = builtins.driver_tfm_hoist(ctx, None, None, {})
    assert not ok
    assert "unsafe" in note


def test_driver_tfm_hoist_no_fileset_decline(tmp_path: Path) -> None:
    """fileset 无同名 .tfm → decline (缺件另有真因，不造空件)。"""
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    ok, note = builtins.driver_tfm_hoist(ctx, None, "ghostfont", {})
    assert not ok
    assert "not present" in note
