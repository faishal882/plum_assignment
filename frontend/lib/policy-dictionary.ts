export interface ResolvedPolicyClause {
  title: string;
  category: "WAITING_PERIOD" | "COPAY" | "SUB_LIMIT" | "EXCLUSION" | "REQUIREMENT" | "COVERAGE" | "SUBMISSION";
  clause_text: string;
  configured_value_label?: string;
}

export function resolvePolicyPath(
  policyPath?: string,
  inputs?: Record<string, unknown>
): ResolvedPolicyClause | null {
  if (!policyPath) return null;

  const path = policyPath.trim();

  // 1. Waiting Periods
  if (path.includes("/waiting_periods/initial_waiting_period_days")) {
    const days = inputs?.waiting_days ?? 30;
    return {
      title: "Initial Waiting Period Clause",
      category: "WAITING_PERIOD",
      clause_text: "Claims for medical treatments undergone within the initial waiting period from member enrollment are excluded.",
      configured_value_label: `Policy Threshold: ${days} Days`,
    };
  }

  if (path.includes("/waiting_periods/pre_existing_conditions_days")) {
    const days = inputs?.waiting_days ?? 365;
    return {
      title: "Pre-Existing Conditions Waiting Period",
      category: "WAITING_PERIOD",
      clause_text: "Treatments related to pre-existing medical conditions require a mandatory waiting period from policy inception.",
      configured_value_label: `Policy Threshold: ${days} Days`,
    };
  }

  if (path.includes("/waiting_periods/specific_conditions/")) {
    const condition = path.split("/").pop() || "specific condition";
    const conditionFormatted = condition.replace(/_/g, " ").toUpperCase();
    const days = inputs?.waiting_days ?? "";
    return {
      title: `Specific Condition Waiting Period (${conditionFormatted})`,
      category: "WAITING_PERIOD",
      clause_text: `Treatment for ${conditionFormatted} requires a specific waiting period before claim eligibility.`,
      configured_value_label: days ? `Policy Threshold: ${days} Days` : `Condition: ${conditionFormatted}`,
    };
  }

  // 2. Co-Pay Clauses
  if (path.includes("/copay_percent")) {
    const category = path.split("/")[2] || "category";
    const categoryName = category.replace(/_/g, " ").toUpperCase();
    const percent = inputs?.copay_percent ?? 10;
    return {
      title: `${categoryName} Co-Payment Clause`,
      category: "COPAY",
      clause_text: `A mandatory co-payment percentage is applied to all admissible expenses under the ${categoryName} category.`,
      configured_value_label: `Co-Pay Rate: ${percent}%`,
    };
  }

  // 3. Sub-Limits
  if (path.includes("/sub_limit")) {
    const category = path.split("/")[2] || "category";
    const categoryName = category.replace(/_/g, " ").toUpperCase();
    return {
      title: `${categoryName} Category Sub-Limit Clause`,
      category: "SUB_LIMIT",
      clause_text: `Maximum cumulative reimbursable limit applicable for ${categoryName} OPD expenses per policy period.`,
      configured_value_label: `Category Limit Applied`,
    };
  }

  // 4. Coverage Limits
  if (path.includes("/coverage/family_floater")) {
    return {
      title: "Family Floater Coverage Clause",
      category: "COVERAGE",
      clause_text: "Policy covers primary employee, spouse, children, and dependent parents under a shared family floater sum insured.",
      configured_value_label: "Family Floater: Enabled (Limit: ₹1,50,000.00)",
    };
  }

  if (path.includes("/coverage/sum_insured_per_employee")) {
    return {
      title: "Annual Sum Insured Per Employee",
      category: "COVERAGE",
      clause_text: "Maximum annual aggregate coverage limit available per primary employee and family.",
      configured_value_label: "Limit: ₹5,00,000.00",
    };
  }

  if (path.includes("/coverage/per_claim_limit")) {
    return {
      title: "Per-Claim Maximum Reimbursable Limit",
      category: "COVERAGE",
      clause_text: "Single claim reimbursement ceiling enforced across all outpatient medical claim submissions.",
      configured_value_label: "Limit: ₹5,000.00",
    };
  }

  if (path.includes("/coverage/annual_opd_limit")) {
    return {
      title: "Annual OPD Overall Limit",
      category: "COVERAGE",
      clause_text: "Total annual ceiling for all outpatient department expenses under the policy terms.",
      configured_value_label: "Limit: ₹50,000.00",
    };
  }

  // 5. Document Requirements
  if (path.includes("/document_requirements/")) {
    const category = path.split("/").pop() || "CATEGORY";
    return {
      title: `Mandatory Document Requirements (${category})`,
      category: "REQUIREMENT",
      clause_text: `Mandatory document proofs (Prescription, Bill, or Report) required for ${category} claim adjudication.`,
      configured_value_label: `Document Proof Verification`,
    };
  }

  // 6. Exclusions
  if (path.includes("/exclusions/")) {
    return {
      title: "Policy General Exclusion Clause",
      category: "EXCLUSION",
      clause_text: "Non-covered procedure, condition, or non-medical item excluded under policy agreement terms.",
      configured_value_label: "Non-Covered Exclusion",
    };
  }

  // 7. Submission Rules
  if (path.includes("/submission_rules/deadline_days_from_treatment")) {
    return {
      title: "Claim Submission Deadline Clause",
      category: "SUBMISSION",
      clause_text: "Claims must be submitted within the specified calendar days from the treatment date.",
      configured_value_label: "Deadline: 30 Days",
    };
  }

  if (path.includes("/submission_rules/minimum_claim_amount")) {
    return {
      title: "Minimum Reimbursable Claim Threshold",
      category: "SUBMISSION",
      clause_text: "Claims below the minimum threshold amount cannot be processed for reimbursement.",
      configured_value_label: "Minimum: ₹500.00",
    };
  }

  // Fallback for any unknown JSON Pointer
  const formattedPointer = path
    .split("/")
    .filter(Boolean)
    .map((s) => s.replace(/_/g, " "))
    .join(" ➔ ");

  return {
    title: `Policy Clause (${formattedPointer || path})`,
    category: "COVERAGE",
    clause_text: `Policy rule provision under section: ${path}`,
    configured_value_label: `Pointer: ${path}`,
  };
}

export function resolveFactRefLabel(ref: string): { label: string; details?: string; iconType: "FACT" | "SNAPSHOT" | "DOCUMENT" } {
  if (ref.startsWith("document-triage:")) {
    return {
      label: "Document Triage & Completeness Verification",
      details: "Document triage proof confirming required medical document presence (Prescription / Itemized Bill)",
      iconType: "DOCUMENT",
    };
  }
  if (ref.startsWith("structured-fixture:")) {
    return {
      label: "Structured Document Role & Classification Record",
      details: "Verified document classification and role mapping proof",
      iconType: "DOCUMENT",
    };
  }
  if (ref.startsWith("utilization:")) {
    return {
      label: "Policy Utilization & YTD Balance Record",
      details: "Year-to-date accumulated policy balance and sub-limit utilization history",
      iconType: "SNAPSHOT",
    };
  }
  if (ref.startsWith("member-version:") || ref.startsWith("member-snapshot:")) {
    return {
      label: "Member Active Enrollment Record Fact",
      details: "Member status verified active under policy enrollment registry",
      iconType: "SNAPSHOT",
    };
  }
  if (ref.startsWith("claim-version:")) {
    return {
      label: "Submitted Claim Packet Snapshot",
      details: "Claim packet details and submission metadata verified",
      iconType: "SNAPSHOT",
    };
  }
  if (ref.startsWith("policy-version:")) {
    return {
      label: "Active Policy Terms Record",
      details: "Policy terms and compiled rule definitions verified",
      iconType: "SNAPSHOT",
    };
  }

  const normalized = ref.toLowerCase();

  if (normalized.includes("member.join") || normalized.includes("join_date")) {
    return { label: "Member Enrollment Date Fact", details: "Member policy join date verified", iconType: "FACT" };
  }
  if (normalized.includes("treatment") || normalized.includes("date")) {
    return { label: "Treatment Date Fact", details: "Medical visit/treatment date verified", iconType: "FACT" };
  }
  if (normalized.includes("claimed") || normalized.includes("amount")) {
    return { label: "Claimed Amount Fact", details: "Total submitted claim amount verified", iconType: "FACT" };
  }
  if (normalized.includes("category")) {
    return { label: "Claim Category Fact", details: "Outpatient medical category verified", iconType: "FACT" };
  }

  if (ref.length > 32 && !ref.includes(" ")) {
    return { label: "System Verification Record", details: "Automated system verification proof", iconType: "DOCUMENT" };
  }

  return { label: `Evidence Fact: ${ref}`, iconType: "FACT" };
}
