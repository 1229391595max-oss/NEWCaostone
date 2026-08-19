"""Server-owned, localized and versioned Ask BizPulse prompt presets."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
from typing import Literal, Mapping

PromptLocale = Literal["en", "zh"]
PROMPT_TEMPLATE_VERSION = "2026-08-15.v1"


class PromptPresetContractInvalid(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PromptPreset:
    id: str
    labels: Mapping[PromptLocale, str]
    templates: Mapping[PromptLocale, str]
    template_version: str
    context_kind: str | None
    intent: str
    max_chars: int
    available: bool

    def template_sha256(self, locale: PromptLocale) -> str:
        return sha256(self.templates[locale].encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ResolvedPrompt:
    question: str
    recommended_question_id: str | None
    prompt_locale: PromptLocale | None
    prompt_template_version: str | None
    prompt_template_sha256: str | None
    fixed_intent: str | None


def _localized(en: str, zh: str) -> Mapping[PromptLocale, str]:
    return MappingProxyType({"en": en, "zh": zh})


_PRESETS = (
    PromptPreset(
        id="monthly_sales_report",
        labels=_localized(
            "Generate this month's sales report",
            "生成本月销售报告",
        ),
        templates=_localized(
            "Generate a sales report for the month covered by the current data release. Include net sales, orders, units, advertising performance, major changes, important SKUs, anomalies and risks, data limitations, and evidence-backed next actions. Cite existing evidence for every number, state missing information explicitly, and do not invent facts.",
            "请根据当前数据版本所覆盖的月份生成销售报告。包括净销售额、订单量、销量、广告表现、主要变化、重点 SKU、异常与风险、数据限制，以及下一步行动建议。所有数字必须引用现有证据；缺失信息必须明确说明，不得补造。",
        ),
        template_version=PROMPT_TEMPLATE_VERSION,
        context_kind=None,
        intent="monthly_sales_report",
        max_chars=2_000,
        available=True,
    ),
    PromptPreset(
        id="profit_changes",
        labels=_localized("Explain profit changes", "分析利润变化原因"),
        templates=_localized(
            "Explain the material profit changes in the current release using only the pinned Profit Bridge facts and evidence. Separate measured drivers, derived conclusions, assumptions, and limitations.",
            "请仅依据当前发布版本中固定的利润桥事实和证据，解释重大利润变化，并区分实测驱动因素、推导结论、假设和限制。",
        ),
        template_version=PROMPT_TEMPLATE_VERSION,
        context_kind="profit_bridge",
        intent="profit_changes",
        max_chars=2_000,
        available=True,
    ),
    PromptPreset(
        id="inventory_risks",
        labels=_localized("Find inventory risks", "查找库存风险"),
        templates=_localized(
            "Identify the material inventory risks in the current release using only the pinned inventory analysis. Prioritize stockout exposure, show supporting evidence, and state data limitations.",
            "请仅依据当前发布版本中固定的库存分析，识别重大库存风险，优先说明缺货风险，并列出支持证据和数据限制。",
        ),
        template_version=PROMPT_TEMPLATE_VERSION,
        context_kind="inventory_analysis",
        intent="inventory_risks",
        max_chars=2_000,
        available=True,
    ),
    PromptPreset(
        id="advertising_performance",
        labels=_localized(
            "Summarize advertising performance",
            "总结广告表现",
        ),
        templates=_localized(
            "Summarize advertising performance for the current release using only authoritative facts. Include spend and available efficiency evidence, explain missing metrics, and do not estimate unavailable values.",
            "请仅依据当前发布版本中的权威事实总结广告表现，包括广告支出和已有的效率证据；明确说明缺失指标，不得估算不可用数值。",
        ),
        template_version=PROMPT_TEMPLATE_VERSION,
        context_kind=None,
        intent="advertising_performance",
        max_chars=2_000,
        available=True,
    ),
    PromptPreset(
        id="forecast_30_days",
        labels=_localized(
            "Summarize the 30-day forecast",
            "总结未来 30 天预测",
        ),
        templates=_localized(
            "Summarize the pinned 30-day forecast for the current release. Explain scenarios, inputs, uncertainty, limitations, and the evidence supporting the forecast without extending the horizon.",
            "请总结当前发布版本中固定的未来 30 天预测，说明情景、输入、不确定性、限制和支持证据，不得延长预测范围。",
        ),
        template_version=PROMPT_TEMPLATE_VERSION,
        context_kind="forecast",
        intent="forecast_30_days",
        max_chars=2_000,
        available=True,
    ),
    PromptPreset(
        id="next_actions",
        labels=_localized("Prioritize next actions", "给出下一步行动建议"),
        templates=_localized(
            "Prioritize the next actions from the current release's existing Action Cards. Preserve their evidence, confidence, limitations, and human-approval status; do not create or approve a new action.",
            "请根据当前发布版本中已有的行动卡确定下一步行动优先级，保留其证据、置信度、限制和人工审批状态；不得创建或批准新行动。",
        ),
        template_version=PROMPT_TEMPLATE_VERSION,
        context_kind="action_cards",
        intent="next_actions",
        max_chars=2_000,
        available=True,
    ),
)


class PromptCatalog:
    def __init__(self, presets: tuple[PromptPreset, ...] = _PRESETS) -> None:
        self._items = presets
        self._by_id = MappingProxyType({item.id: item for item in presets})
        if len(self._by_id) != len(self._items):
            raise ValueError("prompt_preset_id_duplicate")

    @classmethod
    def default(cls) -> "PromptCatalog":
        return cls()

    def ids(self) -> tuple[str, ...]:
        return tuple(item.id for item in self._items)

    def items(self) -> tuple[PromptPreset, ...]:
        return self._items

    def get(self, preset_id: str) -> PromptPreset:
        preset = self._by_id.get(preset_id)
        if preset is None:
            raise PromptPresetContractInvalid("prompt_preset_contract_invalid")
        return preset

    def public_items(self) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "id": preset.id,
                "labels": dict(preset.labels),
                "templates": dict(preset.templates),
                "template_version": preset.template_version,
                "template_sha256": {
                    locale: preset.template_sha256(locale)
                    for locale in ("en", "zh")
                },
                "context_kind": preset.context_kind,
                "intent": preset.intent,
                "max_chars": preset.max_chars,
                "available": preset.available,
            }
            for preset in self._items
        )

    def resolve(
        self,
        *,
        question: str,
        recommended_question_id: str | None,
        prompt_locale: str | None,
        prompt_template_version: str | None,
        prompt_template_sha256: str | None,
        context_kind: str | None,
    ) -> ResolvedPrompt:
        metadata = (
            recommended_question_id,
            prompt_locale,
            prompt_template_version,
            prompt_template_sha256,
        )
        present = tuple(value is not None for value in metadata)
        if any(present) and not all(present):
            raise PromptPresetContractInvalid("prompt_preset_contract_invalid")
        if not any(present):
            return ResolvedPrompt(question, None, None, None, None, None)

        assert recommended_question_id is not None
        assert prompt_locale is not None
        assert prompt_template_version is not None
        assert prompt_template_sha256 is not None
        if prompt_locale not in {"en", "zh"}:
            raise PromptPresetContractInvalid("prompt_preset_contract_invalid")
        locale: PromptLocale = prompt_locale
        preset = self.get(recommended_question_id)
        if (
            not preset.available
            or prompt_template_version != preset.template_version
            or prompt_template_sha256 != preset.template_sha256(locale)
            or question != preset.templates[locale]
            or len(question) > preset.max_chars
            or (
                context_kind is not None
                and context_kind != preset.context_kind
            )
        ):
            raise PromptPresetContractInvalid("prompt_preset_contract_invalid")
        fixed_intent = (
            preset.intent if question == preset.templates[locale] else None
        )
        return ResolvedPrompt(
            question=question,
            recommended_question_id=recommended_question_id,
            prompt_locale=locale,
            prompt_template_version=prompt_template_version,
            prompt_template_sha256=prompt_template_sha256,
            fixed_intent=fixed_intent,
        )
