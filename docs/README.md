# Technical notes (in Russian)

These working notes give the detailed specifications summarised in Sections 2–3 of the paper.

| File | Content |
|---|---|
| `method_v2.md` | Specification of method C1 over the versioned document-level top-k answer contract (Sections 2–3) |
| `numeric_certificate_C1.md` | Derivation of the canonical-score error bounds and the blockwise invariance test (Sections 3.1–3.2) |
| `proof_obligations.md` | Proof obligations, trusted base and guarded numerical domain of the certificate (Sections 3.2, 6.3) |
| `fsum_runtime_audit_C1.md` | Correspondence between `math.fsum` of CPython 3.9.6/arm64 and the analysed algorithm |
| `implementation_numeric_contract.md` | Numerical contract of the implementation and the runtime guards |
| `baseline_adaptations_E04.md`, `baseline_protocol.md` | Exact adaptations of the controls B0–B6 (Section 3.4, Table 1) and the comparison protocol |
| `implementations.md`, `complexity.md`, `pseudocode.txt` | Implementation interfaces, cost analysis and pseudocode of C1 |
| `success_criteria.json` | Success criteria fixed before the comparisons, including the original 10% target (Section 4.3) |

Only files present in this directory are part of the artifact.
