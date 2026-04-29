## Tool Priority

- 按文件名找：`fd`
- 按文本内容找：`rg`（ripgrep）
- 按代码结构/语义找：`sg`（ast-grep）
- 推荐顺序：先 `fd` 缩小文件范围，再 `rg` 定位文本，最后用 `sg` 做结构化确认或重写建议。
- 仅需纯文本匹配时，优先 `rg`，不必强行使用 AST 工具。

### AST-grep Usage（Windows）

- 对复杂结构模式执行前，先说明意图，并先给出将要执行的完整命令。
- 优先使用 `sg` 命令；`ast-grep run` 为等价写法。
- 通用命令模板：`sg -p "<pattern>" <path> --lang <lang>`
- 元变量建议：
    - 单节点匹配使用 `$A`、`$B` 等。
    - 多参数/多节点匹配使用 `$$$ARGS`。
- 常见跨语言查询示例：
    - TypeScript import：`sg -p "import $A from 'node:path'" src --lang ts`
    - JavaScript require：`sg -p "require('node:path')" src --lang js`
    - Java 调试输出：`sg -p "System.out.println($$$ARGS)" src --lang java`
    - Python 打印调用：`sg -p "print($$$ARGS)" src --lang python`
- 建议替换（默认只给建议，不直接自动改代码，除非已获批准）：
    - 搜索：`sg -p "System.out.println($$$ARGS)" src --lang java`
    - 建议替换为：项目统一日志方法（例如 `log.info(...)`）

### Search Hygiene（fd/rg/sg）

- 为保证速度与结果相关性，搜索时排除大体积目录：`.git`、`node_modules`、`coverage`、`out`、`dist`。
- 优先在明确范围内执行（例如 `src`），避免扫描 vendor 与 VCS 目录。
- 示例：
    - `rg -n "pattern" src -g "!{.git,node_modules,coverage,out,dist}"`
    - `fd --hidden --exclude .git --exclude node_modules --exclude coverage --exclude out --exclude dist --type f ".*\\.(java|kt|js|ts|py|go|rs)$" src`
- `ast-grep` 通常会遵循 `.gitignore`；建议直接指定 `src` 避免无关目录：
    - `sg -p "import $A from '@shared/$B'" src --lang ts`
    - 如需进一步控制，请优先在 ignore 文件中添加规则，而不是关闭 ignore 机制。