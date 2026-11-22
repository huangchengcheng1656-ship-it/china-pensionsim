# 验证数据需求与接入规则

## 1. 通用字段和披露边界

每张标准 CSV 都包含以下三个字段：

| 字段 | 规则 |
| --- | --- |
| `dataset_type` | `synthetic`、`public_official` 或 `real_aggregate`；合成样例必须显式使用 `synthetic` |
| `review_status` | 合成为 `not_required`，公开来源为 `source_checked`，真实组级汇总为 `approved` |
| `review_reference` | 真实组级汇总必填，3–64 个 ASCII 字母、数字、点号、连字符或下划线；其他类型留空 |

`real_aggregate` 只允许经过审阅、符合调查或行政数据披露条件的组级结果。校验器拒绝把未审阅数据标为真实汇总，但不能替代披露审查，也不能识别所有隐私风险。

真实个体记录不得进入本发布包。行政模板中的 `person_key` 只用于获准环境内的同轨迹核对，公开交接时应改成合规组级汇总，而不是保留逐人逐月记录。

## 2. CFPS 就业与险种转移：`cfps_transitions.csv`

| 字段 | 含义与单位 |
| --- | --- |
| `wave_pair` | 波次对，格式 `YYYY-YYYY`；训练与留出分别登记 |
| `age_band`、`sex` | 预先声明的年龄带和性别组；性别用 `female`、`male` 或 `all` |
| `employment_from`、`employment_to` | 起止就业状态：`standard`、`nonstandard`、`out`、`unknown` |
| `pension_from`、`pension_to` | 起止自报险种：`worker`、`resident`、`none`、`unknown` |
| `weighted_transitions` | 该转移单元的调查加权重，单位与所用权重一致 |
| `unweighted_n` | 未加权样本人数，非负整数且必须大于零 |
| `effective_n` | 有效样本量，不得超过 `unweighted_n` |
| `missing_share` | 缺答份额，0–1 |

建议流程：先用 2018→2020 估计并冻结参数、公式和源码指纹，再打开 2020→2022 做留出检验。训练与留出必须使用相同状态定义、权重口径和年龄范围。两次波次不能自动证明逐月实际缴费或停复缴。

## 3. CHARLS 在领待遇：`charls_benefits.csv`

| 字段 | 含义与单位 |
| --- | --- |
| `wave` | 调查年份；当前独立核查入口使用 2023 年 |
| `pension_scheme` | `worker` 或 `resident` |
| `age_band`、`sex` | 预先声明的 45 岁及以上确认在领者分组 |
| `weighted_mean_monthly`、`weighted_median_monthly` | 加权月待遇均值和中位数，元/月 |
| `recipient_weight` | 确认在领者的权重和，不是人数 |
| `unweighted_n` | 未加权在领人数 |
| `missing_lower`、`missing_upper` | 缺答影响下界和上界，0–1，且下界不得高于上界 |

调查待遇用于同人群、同月份的独立核查，不能替代行政认定权益、退休类别或银行首款记录。模型侧汇总必须在打开调查晚窗之前冻结。

## 4. 分层公开参数：`regional_parameters.csv`

金额均为元/月。`area_level` 只接受 `province` 或 `city`，`area_name` 是参数实际适用的省或市名称，`province` 保留所属省份。`year` 是适用或观察年份，`source_url` 可填多个 HTTPS 地址并用 `|` 分隔。

- 省级职工行必须填写 `average_wage_monthly`、缴费上下限、`retirement_base_monthly` 和 `effective_from`，不得混入居民基础养老金；平均工资须与登记来源口径一致，缴费下限不得高于上限。
- 市级居民行只填写 `resident_basic_monthly`，不得混入省级职工字段。若公开材料只提供观察时点而首次生效日未知，`effective_from` 必须留空，不能补造日期。

随包公开行的口径：

- 浙江省 2026 年职工缴费基数下限 5,122、上限 25,611、当年新退休人员计发基数 8,537 元/月；平均工资列为来源登记的 2025 年参考值 8,537 元/月。
- 居民基础养老金 390 元/月是杭州市区 2026-04-13 公开观察值，不能据此推断其在 2026 年 1 月已生效，也不能外推至浙江全省。
- `run.py --region 浙江省` 将上述省级职工与市级居民参数用于合成载体，2027 年以后冻结 2026 年参数仅为显式情景，不是官方预测。

`data/public/policy_register.csv` 另行登记全国及地方政策来源、实施状态和模型局限；它不是可直接估计行为的微观数据。

## 5. 官方宏观对齐：`official_macro.csv`

| 字段 | 含义与单位 |
| --- | --- |
| `region`、`year`、`scheme` | 地区、年份及 `worker`/`resident` 险种 |
| `participants`、`contributors`、`recipients` | 参保、实际缴费和领取人数；缴费人数不得高于参保人数 |
| `fund_income_yuan`、`fund_expenditure_yuan` | 同统计范围的基金收入和支出，元/年 |
| `fiscal_subsidy_yuan` | 已明确计入的财政补贴，元/年 |
| `statistical_scope` | 预决算、快报或决算、人群覆盖及是否含财政补贴等口径 |
| `source_url`、`document` | 公开表必须使用 HTTPS 来源和文件名 |

不可把预算拨款、基金收付、期末存量和模型现值混为同一指标。若不同表的人月、金额或风险集口径不同，应分行登记，不做强行拼接。

## 6. 行政同轨迹验证：`admin_validation.csv`

| 字段 | 含义与单位 |
| --- | --- |
| `baseline_month` | 期初观察月，`YYYY-MM` |
| `worker_actual_months`、`worker_deemed_months` | 期初经办认定的职工实际与视同缴费月数 |
| `resident_credited_months` | 期初居民已认定权益月数 |
| `contribution_period_month`、`posting_month` | 缴费所属期与实际入账期；入账不得早于所属期 |
| `contribution_base_yuan` | 该期实际持有的计缴基数，元/月 |
| `transfer_completion_date` | 跨制或跨区转接完成日，`YYYY-MM-DD` |
| `retirement_category` | 经资料或经办确认的退休类别，不以年龄或性别猜测 |
| `assessment_month`、`first_payment_month` | 待遇核定月与首领月；首领不得早于核定 |
| `bank_receipt_yuan` | 同月银行实收，元 |
| `verified_zero_receipt` | 经核零付款为 1，否则为 0；为 1 时实收必须为 0 |

真实验证应选取基期未领且风险集明确的人群，保留同一人的权益变化、后续入账、资格裁定和支付证据。缺失凭证必须保留未知，不能以合成支付代替。训练只能使用先期冻结信息，是否达标、实际申领时点与金额应分开评价。

## 7. 校验和交接

```powershell
python -B data_validation.py
python -B data_validation.py path/to/cfps_transitions.csv path/to/charls_benefits.csv
```

校验包括必填字段、有限非负数、整数人数、比例范围、缺答上下界、样本量关系、日期有效性及顺序、公开来源和真实汇总审阅标记。空白需求表只有表头，需填入数据后再校验。通过校验只表示接口一致，不表示估计、校准或留出验证已经完成。
