r"""xelatex 运行环境/argv mixin（``engine/_xelatex`` 二级缝叶）。

``_XelatexEnv`` 是 ``XelatexEngine`` 的环境臂：kpathsea 缓冲/fontconfig
注册/TEXMFHOME 冒号链 env 构造 + tlmgr/updmap 系单树 env 变体 +
engine_flags 预切与 xelatex 命令行构造。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from typing import Final

from texlate.compile.sandbox import _texmfdist, child_env
from texlate.textutil import env_raw

#: ``compile(flags=…)`` 拒放面：重键输出落点的 flag 会毁掉 ``{stem}.pdf/.log``
#: 按 outdir 回收的约定——这类请求进 ``CompRes.flags_dropped`` 而非 argv。
_OUTPUT_REKEY_PREFIXES: Final = ("-output-directory", "-aux-directory", "-jobname")


class _XelatexEnv:
    """env 构造/命令行 plumbing mixin（实例状态由 ``XelatexEngine.__init__`` 初始化）。"""

    if TYPE_CHECKING:
        # ------------------------------------------------------------ 宿主契约（ty 静态面）
        # ``XelatexEngine.__init__`` 注入的状态。
        texmfhome: Path | None
        halt_on_error: bool
        _fontconfig_memo: tuple[Path | None, str] | None

    def _env(self, extra: dict[str, str] | None) -> dict[str, str]:
        add = dict(extra or {})
        # 单行超长的 legacy 宏转储 (TCI tcilcomm.tex 实测 3MB/行) 会顶穿
        # web2c 默认 buf_size=200000 → `Unable to read an entire line` 硬死。
        # kpathsea cnf 变量可经 env 覆盖, 放宽输入行缓冲即解 (loop1-1706.02464)。
        add.setdefault("buf_size", "8000000")
        # fontspec 裸名查找走 fontconfig——texmf 自带 otf (FontAwesome.otf
        # 等) 未注册必炸 "font X cannot be found"。注入一份把
        # texmf-dist/opentype + usertree 字体注册的 conf（2211.12985 实证：
        # ambient/sandbox 同缺, OSFONTDIR 不吃, FONTCONFIG_FILE 一注即解）。
        fc = self._fontconfig_conf()
        if fc:
            add.setdefault("FONTCONFIG_FILE", fc)
        if self.texmfhome:
            # TEXMFHOME 写冒号链：usertree 居首（可写/优先），ambient
            # TEXMFHOME（缺席时取 kpathsea 默认 ~/texmf）尾随保持可见——
            # 否则宿主 ~/texmf 里的 shim/老包在 fixloop 冷树视角下凭空消失
            # （regress4 假退化根因）。tlmgr/updmap 不认链，走 _usertree_env。
            home_tree = str(self.texmfhome / "home")
            tail = env_raw("TEXMFHOME") or str(Path.home() / "texmf")
            homes = [home_tree] + [e for e in tail.split(":") if e and e != home_tree]
            add.update(
                {
                    "TEXMFHOME": ":".join(homes),
                    "TEXMFVAR": str(self.texmfhome / "var"),
                    "TEXMFCONFIG": str(self.texmfhome / "config"),
                }
            )
        return child_env(add)

    def _fontconfig_conf(self) -> str | None:
        """写一份 fontconfig conf 并返回路径（texmf opentype + usertree 字体注册）。

        ``FONTCONFIG_FILE`` 是整份替换语义——必须 ``<include>`` 系统 conf
        保住宿主机字体面。conf 落 ``usertree/home`` 之下（该目录经
        ``TEXMFHOME`` 链入 ``_bwrap_env_paths`` 挂进沙箱；usertree 根本身
        不在挂载面）；texmfhome 缺席时落 ``~/.cache/texlate/fontconfig/``
        （已列入 ``_bwrap_mounts`` rw）。重写幂等——实例内 memo
        （``_fontconfig_memo``）同 texmfhome 键只写一回：``_env`` 每次
        kpsewhich/tlmgr/updmap spawn 都经本方法，幂等重写此前逐次摊销。
        """
        if (
            self._fontconfig_memo is not None
            and self._fontconfig_memo[0] == self.texmfhome
            and Path(self._fontconfig_memo[1]).is_file()
        ):
            return self._fontconfig_memo[1]
        dist = _texmfdist()
        dirs = []
        if dist:
            dirs.append(str(Path(dist) / "fonts" / "opentype"))
            # truetype 树同注册 (tinos/noto 等 google ttf 家族)——名查找字体
            # 在 truetype 的格此前必炸 fontspec_missing (2609.20064 实证)。
            dirs.append(str(Path(dist) / "fonts" / "truetype"))
        home_ot = (
            self.texmfhome / "home" / "fonts" / "opentype"
            if self.texmfhome
            else Path.home() / "texmf" / "fonts" / "opentype"
        )
        dirs.append(str(home_ot))
        try:
            cdir = (
                self.texmfhome / "home" / "fontconfig"
                if self.texmfhome
                else Path.home() / ".cache" / "texlate" / "fontconfig"
            )
            cdir.mkdir(parents=True, exist_ok=True)
            (cdir / "cache").mkdir(parents=True, exist_ok=True)
            conf = cdir / "fonts.conf"
            body = [
                "<?xml version='1.0'?>",
                "<!DOCTYPE fontconfig SYSTEM 'fonts.dtd'>",
                "<fontconfig>",
                '  <include ignore_missing="yes">/etc/fonts/fonts.conf</include>',
                *(f"  <dir>{d}</dir>" for d in dirs),
                # texmf opentype 数千枚，首扫几秒级——cachedir 落 usertree 内
                # 随格多次重编译摊销（沙箱 HOME 是 tmpfs，不落此即每次重扫）。
                f"  <cachedir>{cdir / 'cache'}</cachedir>",
                "</fontconfig>",
            ]
            conf.write_text("\n".join(body) + "\n", encoding="utf-8")
        except OSError:
            return None  # 写失败不 memo——下回重试（同旧逐次重写语义）
        self._fontconfig_memo = (self.texmfhome, str(conf))
        return str(conf)

    def _usertree_env(self) -> dict[str, str]:
        """tlmgr/updmap 系 env：TEXMFHOME 退链取首元素。

        tlmgr 把 env 值当字面路径——冒号链会被建成名为 ``texA:`` 的目录
        且 tlpdb 判定全炸（实测）。kpathsea 读侧（compile/probe）才吃链。
        """
        env = self._env(None)
        home = env.get("TEXMFHOME")
        if home and ":" in home:
            env["TEXMFHOME"] = home.split(":", 1)[0]
        return env

    @staticmethod
    def _split_flags(flags: Iterable[str] | None) -> tuple[list[str], list[str]]:
        """engine_flags → (进 argv, 丢弃)。

        ``_OUTPUT_REKEY_PREFIXES`` 系 flag 会重键 pdf/log 落点、毁掉按
        outdir 回收产物的约定 → 拒放进 dropped（kpathsea 单双横线等价，
        ``--output-directory=/x`` 同拒）；两 token 形态
        （``-output-directory /x``）把值 token 一并丢——留在 argv 会被
        xelatex 当第二输入文件处理。其余原样直通。
        """
        applied, dropped = [], []
        flist = list(flags or ())
        i = 0
        while i < len(flist):
            fl = flist[i]
            # kpathsea 长选项单双横线等价——归一成单横线再查重键表，
            # 否则 ``--output-directory=/x`` 绕过拒放面把 pdf/log 落点重键。
            norm = "-" + fl.lstrip("-")
            if norm.startswith(_OUTPUT_REKEY_PREFIXES):
                dropped.append(fl)
                if (
                    "=" not in fl
                    and i + 1 < len(flist)
                    and not flist[i + 1].startswith("-")
                ):
                    dropped.append(flist[i + 1])
                    i += 1
            elif fl not in applied:
                applied.append(fl)
            i += 1
        return applied, dropped

    def _cmd(
        self,
        binary: str,
        out: Path,
        main_name: str,
        *,
        best_effort: bool = False,
        flag_toks: Iterable[str] | None = None,
    ) -> list[str]:
        """构造 xelatex 命令行（docs/spec/compile.md 旗标集 + 预切 engine_flags）。

        ``flag_toks`` 是 ``_split_flags`` 已放行的 token——compile() 喂
        ``res.flags_applied``（过滤记账单点在 compile 头段，此处不复切；
        预切也免了同一 ``flags`` 迭代器被二次消费的空放形）。追加在基线
        旗标之后、``main_name`` 之前——kpathsea 选项 last-wins，规则请求
        （如 minted 的 ``-shell-escape``）可压过 ``-no-shell-escape``。
        """
        cmd = [
            binary,
            "-no-shell-escape",
            "-interaction=nonstopmode",
            "-file-line-error",
            "-recorder",
            f"-output-directory={out}",
        ]
        if self.halt_on_error and not best_effort:
            cmd.insert(3, "-halt-on-error")
        for fl in flag_toks or ():
            if fl not in cmd:
                cmd.append(fl)
        cmd.append(main_name)
        return cmd
