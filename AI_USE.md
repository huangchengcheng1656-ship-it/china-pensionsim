# Use of AI assistants / AI 工具使用说明

Large parts of the code, tests and documentation in this repository were drafted with AI coding assistants: OpenAI Codex, Moonshot KIMI and Anthropic Claude. The authors specified the model design, the policy rules to implement and the acceptance criteria; the assistants wrote and revised code under those instructions.

Safeguards used:

- Every policy rule is registered with its legal source in `data/public/policy_register.csv`.
- Frozen regression tests replay sealed synthetic results with a relative tolerance of 1e-12; any change to model output fails the tests.
- Restructuring for the public release was checked by comparing outputs before and after the change byte by byte (demo runs, the 64-arm policy grid, the policy price table, the optimiser and the interruption experiments).

The authors take full responsibility for the content of this repository.

本仓库的大部分代码、测试和文档由 AI 编程助手（OpenAI Codex、月之暗面 KIMI、Anthropic Claude）在作者指令下起草和修改。模型设计、所实现的政策规则和验收标准由作者确定。每条政策规则均登记法规出处；冻结回归测试以 1e-12 相对容差复算封存结果；公开版目录调整前后的输出经逐字节比对一致。作者对仓库内容负全部责任。
