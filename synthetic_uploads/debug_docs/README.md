# Synthetic upload documents

These files are synthetic and safe for local live/debug runs.

## Success set: clean consultation approval
Use frontend form values:

- member_id: `EMP001`
- policy_id: `PLUM_GHI_2024`
- claim_category: `CONSULTATION`
- treatment_date: `2024-11-01`
- claimed_amount: `1500`
- currency: `INR`

Upload:

- `success_consultation_prescription_rajesh.jpg`
- `success_consultation_bill_rajesh.jpg`

Expected recorded-local result: `DECIDED / APPROVED`, approved around `₹1,350.00` because 10% co-pay applies.

## Failure set A: identity mismatch
Use same form values as above, but upload:

- `fail_identity_prescription_rajesh.jpg`
- `fail_identity_bill_arjun.jpg`

Expected result: `ACTION_REQUIRED` due to patient identity conflict: Rajesh Kumar vs Arjun Mehta.

## Failure set B: wrong document type
Use same form values as above, but upload:

- `success_consultation_prescription_rajesh.jpg`
- `fail_wrong_document_second_prescription.jpg`

Expected result: `ACTION_REQUIRED` because consultation requires `PRESCRIPTION` + `HOSPITAL_BILL`, but two prescriptions were uploaded.

## Faishal local demo set
Create/select a local demo member named `Faishal Khan` in the frontend identity selector first. The system assigns the employee/member ID automatically.

Suggested frontend form values:

- member_id: use the auto-assigned ID shown in the selector
- policy_id: `PLUM_GHI_2024`
- claim_category: `CONSULTATION`
- treatment_date: `2024-11-18`
- claimed_amount: `1350`
- currency: `INR`

Core consultation approval upload:

- `faishal_consultation_prescription.pdf`
- `faishal_consultation_bill.pdf`

Extra optional/wrong-document classification probes:

- `faishal_pharmacy_bill.pdf`
- `faishal_diagnostic_report.pdf`
