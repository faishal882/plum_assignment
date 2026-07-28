from claims_backend.domain.adjudication import (
    AdjudicationProposal,
    AdjudicationRecommendation,
)
from claims_backend.domain.claims import (
    MemberDeduction,
    MemberExplanation,
    MemberLineItemExplanation,
)


def render_member_explanation(proposal: AdjudicationProposal) -> MemberExplanation:
    dental_items = tuple(
        result
        for result in proposal.rule_results
        if result.reason_code
        in {"DENTAL_LINE_ITEM_COVERED", "DENTAL_LINE_ITEM_EXCLUDED"}
    )
    if dental_items:
        line_items = tuple(
            MemberLineItemExplanation(
                concept=_required_string(result.inputs.get("concept")),
                label=_required_string(result.inputs.get("label")),
                claimed_paise=_required_integer(
                    result.inputs.get("line_item_paise")
                ),
                approved_paise=(
                    _required_integer(result.inputs.get("line_item_paise"))
                    if result.reason_code == "DENTAL_LINE_ITEM_COVERED"
                    else 0
                ),
                status=(
                    "APPROVED"
                    if result.reason_code == "DENTAL_LINE_ITEM_COVERED"
                    else "REJECTED"
                ),
                reason_code=result.reason_code,
            )
            for result in dental_items
        )
        excluded = tuple(
            item for item in line_items if item.status == "REJECTED"
        )
        excluded_paise = sum(item.claimed_paise for item in excluded)
        return MemberExplanation(
            summary=(
                f"{_format_rupees(proposal.approved_paise)} approved; "
                f"{_format_rupees(excluded_paise)} excluded from the dental claim."
            ),
            deductions=tuple(
                MemberDeduction(
                    code=item.reason_code,
                    label=f"{item.label} is excluded by the dental policy.",
                    amount_paise=item.claimed_paise,
                )
                for item in excluded
            ),
            line_items=line_items,
        )

    exclusion = next(
        (
            result
            for result in proposal.rule_results
            if result.reason_code == "EXCLUDED_CONDITION"
        ),
        None,
    )
    if (
        proposal.recommendation is AdjudicationRecommendation.REJECTED
        and exclusion is not None
    ):
        label = _required_string(exclusion.inputs.get("exclusion_label"))
        return MemberExplanation(
            summary=(
                f"This claim is excluded because {label} "
                "are not covered by the policy."
            ),
            deductions=(
                MemberDeduction(
                    code=exclusion.reason_code,
                    label=label,
                    amount_paise=-exclusion.adjustment_paise,
                ),
            ),
        )

    waiting = next(
        (
            result
            for result in proposal.rule_results
            if result.reason_code == "WAITING_PERIOD"
        ),
        None,
    )
    if (
        proposal.recommendation is AdjudicationRecommendation.REJECTED
        and waiting is not None
    ):
        condition = _required_string(waiting.inputs.get("condition")).replace("_", " ")
        eligible_from = _required_string(waiting.inputs.get("eligible_from"))
        waiting_days = _required_integer(waiting.inputs.get("waiting_days"))
        return MemberExplanation(
            summary=(
                f"{condition.capitalize()}-related claims are eligible from "
                f"{eligible_from}; this treatment occurred during the "
                f"{waiting_days}-day waiting period."
            ),
            deductions=(),
        )

    copay = next(
        (
            result
            for result in proposal.rule_results
            if result.reason_code == "CATEGORY_COPAY_APPLIED"
        ),
        None,
    )
    if copay is not None and copay.adjustment_paise < 0:
        percent = _required_integer(copay.inputs.get("copay_percent"))
        category = copay.rule_id.removeprefix("amount.").removesuffix(".copay")
        deduction = -copay.adjustment_paise
        label = f"{percent}% {category.replace('_', ' ')} co-pay"
        return MemberExplanation(
            summary=(
                f"{_format_rupees(proposal.approved_paise)} approved after a {label}."
            ),
            deductions=(
                MemberDeduction(
                    code=copay.reason_code,
                    label=label,
                    amount_paise=deduction,
                ),
            ),
        )

    return MemberExplanation(
        summary=(
            f"{_format_rupees(proposal.approved_paise)} "
            f"{proposal.recommendation.value.casefold()}."
        ),
        deductions=(),
    )


def _required_string(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("Explanation trace is missing a required string input.")
    return value


def _required_integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Explanation trace is missing a required integer input.")
    return value


def _format_rupees(paise: int) -> str:
    return f"₹{paise / 100:,.2f}"
