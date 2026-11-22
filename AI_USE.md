# Use of AI assistants / AI 工具使用说明

OpenAI Codex, Moonshot KIMI and Anthropic Claude assisted in drafting and revising large parts of the code, tests and documentation. The authors specified the model design, policy rules and acceptance criteria and are responsible for the released content.

The package includes a policy-source register, synthetic examples and tests. Regression tests compare fixed examples distributed with the package, using a relative tolerance of 1e-12 and an absolute tolerance of 1e-9 for floating-point values; their scope is defined in `tests/test_frozen_regression.py`. Boundary tests in `tests/test_boundaries.py` check eligibility timing, wage tax and input contracts against hand-computed values. The implementation status of each rule and the scenario assumptions are listed in the policy register; the empirical validation design is in `docs/validation_protocol.md`.

本项目使用 OpenAI Codex、Moonshot KIMI 和 Anthropic Claude 辅助起草和修改大部分代码、测试与文档。作者确定模型设计、拟实现的政策规则和验收要求，并对发布内容负责。

发布包提供政策来源登记、合成示例和测试。回归测试比较随包固定样例的结果，浮点数比较使用相对容差 1e-12 和绝对容差 1e-9，比较范围见 `tests/test_frozen_regression.py`；`tests/test_boundaries.py` 以手算值检查领取时点、工资个税和输入合同。规则实现状态和情景假设见政策登记表，经验验证方案见 `docs/validation_protocol.md`。
