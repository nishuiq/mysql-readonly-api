# Agent Guidance

- 查找文件使用 `rg --files`，查找文本使用 `rg`。
- 仅在纯文本搜索无法判断代码结构时使用 AST 工具。
- 搜索应限定在相关目录，避免扫描生成目录和大体积目录。

## 项目约定

- 临时测试环境、下载包、日志和生成文件放在项目 `temp/` 下，该目录不提交。
- 服务配置必须完整显式填写，不为缺项补值；未知字段统一报错，不保留旧字段的专属处理。
- `query.limit` 同时作为请求省略 `limit` 时的返回行数和单次硬上限，请求只能缩小该值。

## Python 注释与 Docstring

- 模块、公开 class、公开函数与方法、非显然的内部边界使用中文 Google-style docstring，首行直接说明用途。
- 有 docstring 的非测试函数与方法，将除 `self` 和 `cls` 之外的具名参数逐项写入 `Args:`。
- 返回非 `None` 时使用 `Returns:`，generator 使用 `Yields:`；说明空值、失败和调用方需要理解的边界。
- 调用方需要理解和处理的契约异常使用 `Raises:`；不把偶发实现错误写成公开契约。
- 已有类型注解时不在 docstring 重复类型；只补充单位、约束、默认行为和注解无法表达的语义。
- class docstring 说明实例代表什么。
- 每个显式 `__init__` 都有自己的 docstring，首行说明创建的对象；按需要说明 `Args:` 和 `Raises:`，不写 `Returns:`。
- 不为继承构造函数或 dataclass 自动生成的 `__init__` 伪造独立 docstring。
- 普通 class 在显式 `__init__` 中首次建立实例字段时，使用 `self.name: Type = value`，下一条语句紧邻一行 attribute docstring。
- 字段说明只解释状态、必要的单位、所有权、生命周期或有效条件；不重复名称、类型、默认值，不写“用于保存”或完整流程，后续赋值不重复注解和说明。
- dataclass 字段使用 class-level 类型注解，由 class docstring 的 `Attributes:` 逐项说明，不再为同一字段添加实例赋值和 attribute docstring。
- dataclass 显式自定义构造时，`Args:`、`Raises:` 说明构造输入和失败，`Attributes:` 说明构造后字段，不互相替代或复制。
- 每个 `test_*` 使用简短中文 docstring 直接说明结论，不以“测试”或“验证”复述动作，也不为 fixture 参数写 `Args:`。
- 复杂测试只在关键准备、触发或断言边界补充少量流程注释。
- 项目自写的 Python `#` 注释和各类 docstring 不使用中文全角句号 `。`；英文 `.`、问号、感叹号、URL、路径、文件名、小数、版本、缩写和代码点号保持原样，不机械删除。
- 普通正式文档和用户可见文案不适用 Python 源码标点规则。
