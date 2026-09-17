# arxiv-fuzz — arxiv/ 非 unpack 模块对抗性 property tests

> 2026-09-17 收口。交付 `tests/test_fuzz_arxiv.py`（~1400 行，commit `e31ba0e`）：**33 passed + 10 xfailed(strict)**，ruff check/format 双净。全离线 MockTransport+注入时钟；unpack 未重复覆盖（既有 fuzz 已盖）。

## 覆盖矩阵（模块 → 性质）

- **fetch.py**：normalize_arxiv_id 随机汤不抛+钉版契约+两步不动点（2×2000）；合法 id round-trip；`_parse_head` 随机 header 组合字段契约（400）；`_retry_delay` 恶意 Retry-After；`acquire_source` 端到端情景 fuzz（150×随机 id/HEAD 态/GET 态/body/预铺缓存/离线臂）：结果归约不崩、entry↔status 双射、meta.json 字段+fetched_at 格式、缓存根无 .staging-/.old- 残渣；瞬态码重试上界 4/host（顺带钉 failover 只对异常/park 触发语义）。
- **sniff.py**：随机字节汤只抛 SniffError+kind↔payload oracle（800）；gzip round-trip + ustar@257 判 TAR；解压上限恰界；变异 gzip 400。
- **check_pdf_wrapper**：随机 TeX 汤字段逻辑恒真（is_wrapper⇔includepdf∧stub 等，500）+ 定向。
- **_texutil.strip_comments**：行数守恒+幂等+行尾无白（400×keep_verbatim 两臂）。
- **ratelimit.py**：path_class 四类封闭（1000）；jitter 确定性+[1±span] 界；随机 ops 模型（400 步：异常集封闭+预算上界+park 自洽）；状态 round-trip；损坏状态 fuzz（错型/负值/垃圾字节）；跨日 rollover。
- **cache.py**：find_versions 任意 id 不抛+升序+glob 元字符/前导斜杠全拒（300）；get 对 UTF-8 可解垃圾 meta→miss；commit→get round-trip 无残渣（60）；entry_dir 逃逸矩阵（resolve 后判逃，折回形放行）。
- **meta.py**：fetch_metadata 双源任意 XML body 不抛（400，池含实体炸弹/截断/错误 entry/墓碑/乱序版本史）；bomb→OAI 兜底定向；resolve_version want∈{want,None}；degrade 全 reason×随机探活结局契约；`_rfc822_to_iso` 原样或 ISO-Z。
- **locate.py**：随机文件树 120 棵（snippet 汤/自环互环 input/dangling+dir symlink/二进制体）→ 不抛+main∈candidates、order 无重复以 main 起头、dead∩order=∅、warning 前缀白名单、同树两次全等；`_norm_arg` 任意输入→POSIX 相对路径或 None（1500）；missing/file root。

## 缺陷台账（全实证复现，10 个 strict xfail 钉）

| # | 缺陷 | 位置 | 影响 | 修法 |
|---|------|------|------|------|
| D1 | 无护 `int()` | fetch.py:192/197/416 | cd 版本号 >4300 位→ValueError 逃逸 acquire_source；content-length latin-1 `²`（isdigit 真 int 假）同型；cd 不受 h11 帧校验——**wire 可达** | int() 包 try 或先 isascii()+isdigit() |
| D2 | cache meta 漏 UnicodeDecodeError | cache.py:104 `except (OSError, JSONDecodeError)` | 非 UTF-8 meta.json 逃逸「损坏=miss」契约；_head_phase:528/_offline_phase 不捕 → 在线/离线两臂 acquire 整体崩 | except 加 ValueError 或收窄到读取级 |
| D3 | `\d` UNICODE 语义收全角/阿-印数字 id | fetch.py:148-149 | 不可能存在的 id 过校验烧请求；与 cache._SAFE_GLOB_ID(ASCII) 不对称→commit 收、find_versions 拒、get_latest 对已存在条目失明（另有非 xfail 实证钉） | 两 id 正则加 re.ASCII |
| D4 | `int(1e999)` → OverflowError 逃逸容错网 | ratelimit.py:143/148 | 损坏状态文件让构造即崩 | except 加 OverflowError |
| D5 | `Retry-After: 1e999` → float inf → `time.sleep(inf)` OverflowError 即刻崩 | fetch.py:216-222 `_retry_delay` | **wire 可达** | isfinite 判 + 封顶（min(ra,300)） |
| D6 | `_gunzip` 漏 `zlib.error`（纯 Exception 非 OSError 子类） | sniff.py:83 | deflate 中段损坏穿透 SniffError 契约 → fetch.py:403 `except SniffError` 拦不住 → 穿出 acquire_source；随机变异 177/400 逃逸；损坏 e-print wire 可达崩溃 | except 加 zlib.error |

## 未钉观察项（实证未达缺陷线）

- locate.py:313 `lowermap` 由 set 构建→大小写碰撞赢家随 PYTHONHASHSEED 变（进程内确定已钉，跨机不稳，改 `sorted(fileset)` 即稳）。
- `Retry-After: 999999999` 有限大值无上限 sleep（~31 年）——D5 有限兄弟，建议同钉 cap。
- meta.py:361 `_VER_TAIL_RE` int() 同 D1 族（需 arxiv.org 自发畸形 Location，可达面窄）。
- entry_dir("\x00") / commit staging-meta 非 UTF-8 → 非 CacheError（acquire 侧 _valid_id 先拒 NUL / 调用方捕 ValueError 兜底，可接受）。
- `_across_hosts` 对瞬态 status 不做 host failover——现规格已钉，若意图「503 换镜像」则语义待确认。
