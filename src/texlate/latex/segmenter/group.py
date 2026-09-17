r"""``latex/segmenter`` 子模块——god-class 机械拆分（行为零变）。"""

from __future__ import annotations

from bisect import (
    bisect_left,
)
from typing import TYPE_CHECKING

from texlate.latex.model import (
    ArgSpec,
    PhType,
    env_opt_is_format,
)
from texlate.latex.tables import (
    ARG_TRANSPARENT_ENVS,
    ENV_MANDATORY_ARG,
    MATH_ENVS,
    PROTECTED_ENVS,
    VERBATIM_ENVS,
    argspec_lookup_env,
    looks_like_colspec,
)

from ._common import (
    _GRP_BSBS_CONTENT_RX,
    _GRP_SCAN_CAP,
    _GRP_TAIL_CAP,
    _chunk_spec_cached,
)

if TYPE_CHECKING:
    import re

    from texlate.latex.model import ArgspecEntry
    from texlate.latex.mouth import (
        Tok,
    )

r"""``Segmenter`` 组内再生保护段（``_grp_*`` 单遍扫描器族）。"""


class _Group:
    def _grp_ph(self, typ: PhType, body: str) -> str:
        r"""组内 surface ph：先挂 ``_run_pending``。

        run 转 chunk 才入 ``ph_map``——literal 冲刷只渲染 ident，surface
        ph 若直登记必成 dead_ph。
        """
        return self.state.issuer.new(
            typ, body, self._run_pending, self.state.ph_reserved
        )

    @staticmethod
    def _cat_surf(out: list[str], s: str) -> None:
        r"""Surface 段追加。

        ``\``-引导且字母结尾的元素（控制词渲染）后随字母开头元素时插
        ``" "``——TeX 控制词吞空格的 detokenize 对价。展开组 token pos
        指调用点、无 gap 字节可恢复（``_gap_surface`` 只救 gen=0），不补
        则 ``{\bf X}`` 展开成 ``\bfX``（未定义控制词 + 逃逸翻译）。
        """
        if (
            out
            and s[:1].isalpha()
            and out[-1].startswith("\\")
            and out[-1][-1:].isalpha()
        ):
            out.append(" ")
        out.append(s)

    def _grp_surfs(self, toks: list[Tok]) -> str:
        out: list[str] = []
        for t in toks:
            self._cat_surf(out, self._tok_surface(t))
        return "".join(out)

    def _grp_envtag(self, toks: list[Tok], i: int) -> tuple[str, int] | None:
        r"""``\\begin``/``\\end`` + ws + ``{name}`` → ``(name, j_end)``；失配 None。

        主流对价：``_env_name``——前扫跨 space 与 ``eol_par``（断行
        env tag 收名），名内 ``eol_par`` 即失败（R6 主流同规）。
        """
        n = len(toks)
        j = i + 1
        while j < n and toks[j].kind in ("space", "eol_par"):
            j += 1
        if j >= n or toks[j].kind != "lbrace":
            return None
        depth = 1
        j += 1
        parts: list[str] = []
        while j < n:
            x = toks[j]
            if x.kind == "eol_par":
                return None
            if x.kind == "lbrace":
                depth += 1
            elif x.kind == "rbrace":
                depth -= 1
                if depth == 0:
                    return "".join(parts), j + 1
            parts.append(self._tok_surface(x))
            j += 1
        return None

    def _grp_env_macro(self, t: Tok) -> tuple[str, str] | None:
        r"""组内 env_begin/env_end 宏端点 → ``(kind, target_env)``；非宏 None。"""
        m = self.state.macros.resolve(self.state.macros.lookup(t.text))
        kind = getattr(m, "kind", "")
        if kind in ("env_begin", "env_end"):
            return kind, getattr(m, "target_env", "")
        return None

    def _grp_find_env_end(  # noqa: C901 — begin/end/cs-end/宏端点四臂单遍深度扫描平铺
        self, toks: list[Tok], i: int, env: str
    ) -> int | None:
        r"""``i`` 起找配对 ``\\end{env}``（同名 begin/宏端点计深度）→ j_end。"""
        target = env.rstrip("*")
        depth = 1
        j = i
        while j < len(toks) and j - i < _GRP_SCAN_CAP:
            x = toks[j]
            if x.kind == "cs" and x.text in ("begin", "end"):
                hit = self._grp_envtag(toks, j)
                if hit is not None:
                    n2, e = hit
                    if n2.rstrip("*") == target:
                        depth += 1 if x.text == "begin" else -1
                        if depth == 0:
                            return e
                    j = e
                    continue
            elif x.kind == "cs":
                # ``\end<env>`` 字面端点（csname 合成/旧式）——主流
                # ``_find_env_end`` 同名判据的组内镜像（R1）
                if x.text == "end" + target:
                    depth -= 1
                    if depth == 0:
                        return j + 1
                    j += 1
                    continue
                em = self._grp_env_macro(x)
                if em is not None and em[1].rstrip("*") == target:
                    depth += 1 if em[0] == "env_begin" else -1
                    if depth == 0:
                        return j + 1
            j += 1
        return None

    def _grp_math_end(self, toks: list[Tok], i: int) -> int | None:
        r"""Mathshift 配对（``$$`` 双 token 形）→ 闭界 j（含）；未中 None。"""
        dbl = i + 1 < len(toks) and toks[i + 1].kind == "mathshift"
        j = i + 2 if dbl else i + 1
        n = len(toks)
        while j < n and j - i < _GRP_SCAN_CAP:
            if toks[j].kind == "mathshift":
                if dbl:
                    if j + 1 < n and toks[j + 1].kind == "mathshift":
                        return j + 2
                    j += 1
                    continue
                return j + 1
            j += 1
        return None

    def _grp_delim_end(self, toks: list[Tok], i: int, want: str) -> int | None:
        r"""``\\[``/``\\(`` 配对 ``\\]``/``\\)`` → j_end；未中 None。"""
        j = i + 1
        n = len(toks)
        while j < n and j - i < _GRP_SCAN_CAP:
            x = toks[j]
            if x.kind == "cs" and x.text == want:
                return j + 1
            j += 1
        return None

    @staticmethod
    def _grp_bal(  # noqa: C901 — 两定界族各一段，平铺即规则
        toks: list[Tok], i: int, *, brace: bool
    ) -> int | None:
        """``{…}``/``[…]`` 平衡组 → 闭界 j（含）；``eol_par``/EOF 止 None。

        主流对价：``_collect_group``（源侧拉取版，``eol_par`` 当内容不判
        段界——两侧 par 规则刻意不同，改一侧前先核对另一侧调用语境）。
        """
        depth = 0
        for j in range(i, len(toks)):
            x = toks[j]
            if x.kind == "eol_par":
                return None
            if brace:
                if x.kind == "lbrace":
                    depth += 1
                elif x.kind == "rbrace":
                    depth -= 1
                    if depth == 0:
                        return j + 1
            elif x.kind == "other":
                if x.text == "[":
                    depth += 1
                elif x.text == "]":
                    depth -= 1
                    if depth == 0:
                        return j + 1
        return None

    def _grp_call_end(self, toks: list[Tok], i: int, mand: int) -> int:
        r"""Cs + ``*``? + ``[opt]``≤3 + ``{arg}``≤mand → j_end（``_protect_cs`` 镜像）。"""
        n = len(toks)
        j = i + 1
        if j < n and toks[j].kind == "other" and toks[j].text == "*":
            j += 1
        for _ in range(3):
            k = j
            while k < n and toks[k].kind == "space":
                k += 1
            if k < n and toks[k].kind == "other" and toks[k].text == "[":
                e = self._grp_bal(toks, k, brace=False)
                if e is None:
                    break
                j = e
                continue
            break
        for _ in range(mand):
            k = j
            while k < n and toks[k].kind == "space":
                k += 1
            if k < n and toks[k].kind == "lbrace":
                e = self._grp_bal(toks, k, brace=True)
                if e is None:
                    break
                j = e
                continue
            break
        return j

    @staticmethod
    def _grp_skip_ws(toks: list[Tok], j: int) -> int:
        r"""space/eol_par 前跳（``_read_skipws`` 的组内对价）。"""
        while j < len(toks) and toks[j].kind in ("space", "eol_par"):
            j += 1
        return j

    def _grp_tail_end(self, toks: list[Tok], i: int, rx: re.Pattern[str]) -> int | None:
        r"""``toks[i:]`` 非文本尾参扫 → j_end；形不合 → None。

        主版 ``_tail_scan_end``（字节正则）的组内对价：surface join 后
        ``_GRP_TAIL_CAP`` 字符窗内匹配，匹配界必须恰在 token 界（切进
        token 内部 → 不匹配）；``eol_par`` 止扫（par 边界不跨）。
        """
        n = len(toks)
        parts: list[str] = []
        bounds = [0]
        j = i
        total = 0
        while j < n and total < _GRP_TAIL_CAP:
            x = toks[j]
            if x.kind == "eol_par":
                break
            s = self._tok_surface(x)
            parts.append(s)
            total += len(s)
            bounds.append(total)
            j += 1
        m = rx.match("".join(parts))
        if m is None or m.end() == 0:
            return None
        e = m.end()
        k = bisect_left(bounds, e)
        if k >= len(bounds) or bounds[k] != e:
            return None  # 匹配界落 token 内（cs 名被尾参切断）——不吃半截
        return i + k

    def _grp_tikz_end(self, toks: list[Tok], i: int) -> int | None:
        r"""组内裸 ``\tikz <path>;`` 的 ``;`` 定界扫描 → j_end；非路径形 → None。

        ``_tikz_tail_end``（字节版）的 token 对价：首非空 token 须是
        cs/``(``/``[``（path 起点族）；``{..}``/``[..]`` 深度内 ``;``
        不算界；``eol_par``/深度外闭括/``\end`` cs 即中止（R8）。
        """
        n = len(toks)
        j = i + 1
        while j < n and toks[j].kind == "space":
            j += 1
        if j >= n or not (
            toks[j].kind == "cs" or (toks[j].kind == "other" and toks[j].text in "([")
        ):
            return None
        depth = 0
        while j < n and j - i < _GRP_SCAN_CAP:
            x = toks[j]
            if x.kind == "eol_par" or (x.kind == "cs" and x.text == "end"):
                return None
            if x.kind == "lbrace" or (x.kind == "other" and x.text == "["):
                depth += 1
            elif x.kind == "rbrace" or (x.kind == "other" and x.text == "]"):
                if depth == 0:
                    return None  # 越过所在组界
                depth -= 1
            elif x.kind == "other" and x.text == ";" and depth == 0:
                return j + 1
            j += 1
        return None

    def _grp_bsbs(self, toks: list[Tok], i: int) -> int | None:
        r"""组内 ``\\`` 的可选 dimen 参 → j_end；``\\[5pt]``/``\\*[2em]`` 命中。

        ``_BSBS_OPT_RX`` 的 token 版：``*``? + ``[atom]``——内容非 dimen
        （``\\[x]`` 形）→ None 回落逐字。
        """
        n = len(toks)
        j = i + 1
        if j < n and toks[j].kind == "other" and toks[j].text == "*":
            j += 1
        while j < n and toks[j].kind == "space":
            j += 1
        if j < n and toks[j].kind == "other" and toks[j].text == "[":
            e = self._grp_bal(toks, j, brace=False)
            if e is not None and _GRP_BSBS_CONTENT_RX.fullmatch(
                self._grp_surfs(toks[j + 1 : e - 1])
            ):
                return e
        return None

    def _grp_spec_args_end(  # noqa: C901, PLR0912, PLR0915 — argspec 字母各一支，平铺即 _eat_env_args_spec 组内镜像
        self,
        toks: list[Tok],
        j: int,
        spec: list[ArgSpec],
        roles: tuple[str, ...],
        env: str | None,
    ) -> int:
        r"""Argspec 位序走参的组内 token 版（``_eat_env_args_spec`` 镜像）。

        返回连续消费的非文本参后界——``text``/``opt-text`` 角色或参数缺席
        处停（其后 token 留 surface 主流，同 ``_unread_args`` 语义）。
        ``env`` 非空时可选位过 ``env_opt_is_format`` 闸（定理标题不收——
        F6 同规）；None 则可选位照常消费（命令可选参无标题歧义）。
        """
        n = len(toks)
        end = j
        k = j
        for si, s in enumerate(spec):
            role = roles[si] if si < len(roles) else "skip"
            while k < n and toks[k].kind == "space":
                k += 1
            if k >= n or toks[k].kind == "eol_par":
                break
            x = toks[k]
            if s.kind in ("m", "v"):
                if x.kind == "lbrace" or (x.kind == "other" and x.text == "["):
                    # ``m`` 认 ``[`` 定界组（``_args_tok`` :3955 同规）——
                    # ``restatable[N]{t}{c}`` 的 ``[N]`` 参组内不被 ``m``
                    # 吃掉则 ``]{t}{c}`` 漏进 surface
                    e = self._grp_bal(toks, k, brace=x.kind == "lbrace")
                    if e is None:
                        break
                    if role in ("text", "opt-text"):
                        break  # 文本参停界——k 不前推（主流 unread 同位）
                    k = end = e
                    continue
                if x.kind == "cs":
                    break  # 单 token 参不跨 '\'（BUG1 同规）
                k += 1  # 单 token 参（env 路 allow_single_token=True 同规）
                end = k
                continue
            if s.kind == "n":
                # 裸 cs 名参（``\setlength\parskip{4pt}``）：cs token 直收
                # 或 ``{..}``/``[..]`` 组——其余形失配即终止（强制参同 m）
                if x.kind == "cs":
                    k += 1
                    end = k
                    continue
                if x.kind == "lbrace" or (x.kind == "other" and x.text == "["):
                    e = self._grp_bal(toks, k, brace=x.kind == "lbrace")
                    if e is None:
                        break
                    if role in ("text", "opt-text"):
                        break
                    k = end = e
                    continue
                break
            if s.kind in ("o", "O"):
                if x.kind == "other" and x.text == "[":
                    e = self._grp_bal(toks, k, brace=False)
                    if e is None:
                        break
                    if role in ("text", "opt-text"):
                        break
                    if env is not None and not env_opt_is_format(
                        env, self._grp_surfs(toks[k + 1 : e - 1])
                    ):
                        break  # 定理标题正文不收——回吐随主流
                    k = end = e
                continue
            if s.kind == "s":
                if x.kind == "other" and x.text == "*":
                    k += 1
                    end = k
                continue
            if s.kind == "t" and s.delim:
                if x.text == s.delim[0]:
                    k += 1
                    end = k
                continue
            if s.kind in ("d", "D", "r", "R") and s.delim:
                op, cl = s.delim[0], s.delim[-1]
                if x.text != op:
                    if s.kind in ("r", "R"):
                        break
                    continue
                k2 = k + 1
                while k2 < n and toks[k2].text != cl and toks[k2].kind != "eol_par":
                    k2 += 1
                if k2 >= n or toks[k2].kind == "eol_par":
                    break
                if role in ("text", "opt-text"):
                    break
                if (
                    env is not None
                    and s.delim != "<>"
                    and not env_opt_is_format(env, self._grp_surfs(toks[k + 1 : k2]))
                ):
                    break
                k = k2 + 1
                end = k
                continue
            # 'e'/'b'/无 delim：不消费
        return end

    def _argspec_env(self, env: str, reg: object | None) -> ArgspecEntry | None:
        r"""Argspec env 条目查询——``_handle_env_begin`` 族表门控同集。"""
        if (
            reg is not None
            or env in VERBATIM_ENVS
            or env in MATH_ENVS
            or env in PROTECTED_ENVS
            or env in ARG_TRANSPARENT_ENVS
            or env in ENV_MANDATORY_ARG
        ):
            return None
        return argspec_lookup_env(env, self.state.pkgs)

    def _grp_env_args_end(  # noqa: C901, PLR0912 — opt/mand/colspec 三段参数尾扫平铺即行序
        self,
        toks: list[Tok],
        j: int,
        env: str,
        reg: object | None,
        ae: ArgspecEntry | None,
    ) -> int:
        r"""``\begin{env}``/env_begin 宏端点尾参的组内对价（``_eat_env_args``）。

        ``ae`` 带签名 → ``_grp_spec_args_end`` 位序走参；否则版式 ``[opt]``
        （``env_opt_is_format`` 闸）+ ``ENV_MANDATORY_ARG``/``reg.spec``
        的 ``{m}`` 数吃进 ENVTAG 界——否则 preamble ``{lRLc}`` 这类非文本
        参裸进 surface 被翻译（``Illegal pream-token``，loop1 slots⑤）。
        """
        if ae is not None and ae.signature:
            return self._grp_spec_args_end(
                toks, j, _chunk_spec_cached(ae.signature), ae.arg_roles, env
            )
        n = len(toks)
        k = j
        while k < n and toks[k].kind == "space":
            k += 1
        if k < n and toks[k].kind == "other" and toks[k].text == "[":
            e = self._grp_bal(toks, k, brace=False)
            if e is not None and env_opt_is_format(
                env, self._grp_surfs(toks[k + 1 : e - 1])
            ):
                j = e
        mand = 1 if env in ENV_MANDATORY_ARG else 0
        if reg is not None:
            mand = max(mand, sum(1 for a in getattr(reg, "spec", ()) if a.kind == "m"))
        for _ in range(mand):
            k = j
            while k < n and toks[k].kind == "space":
                k += 1
            if k >= n or toks[k].kind != "lbrace":
                break
            e = self._grp_bal(toks, k, brace=True)
            if e is None:
                break
            j = e
        if mand == 0:
            # 列型前导 peek 的组内镜像（R3）——首 ``{..}`` 形似列参即吃进
            k = j
            while k < n and toks[k].kind == "space":
                k += 1
            if k < n and toks[k].kind == "lbrace":
                e = self._grp_bal(toks, k, brace=True)
                if e is not None and looks_like_colspec(
                    self._grp_surfs(toks[k + 1 : e - 1])
                ):
                    j = e
        return j

    def _grp_probe_end(self, toks: list[Tok], i: int) -> int | None:
        r"""未知命令探针的组内版（``_handle_unknown_cs``：``[opt]``? + ``{m}``×6、禁单 token 参）。

        任一参数命中 → j_end；全缺席 → None。
        """
        n = len(toks)
        j = i + 1
        hit = False
        k = j
        while k < n and toks[k].kind == "space":
            k += 1
        if k < n and toks[k].kind == "other" and toks[k].text == "[":
            e = self._grp_bal(toks, k, brace=False)
            if e is not None:
                j = e
                hit = True
        for _ in range(6):
            k = j
            while k < n and toks[k].kind == "space":
                k += 1
            if k >= n or toks[k].kind != "lbrace":
                break
            e = self._grp_bal(toks, k, brace=True)
            if e is None:
                break
            j = e
            hit = True
        return j if hit else None

    # -------------------------------------------------------- 跨边界待绑参
